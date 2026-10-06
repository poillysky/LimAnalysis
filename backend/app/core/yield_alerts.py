"""近 3 小时机台不良率标红 → 按当前班次从排班表找人。"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.ads_query import (
    _APPEARANCE_ITEMS,
    _enabled_project,
    query_machine_cavity_breakdown,
)
from app.core.db import MetaSession
from app.core.duty_roster import list_roster
from app.core.meta_init import CAVITY_ALERT_RULES_KEY, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.personnel import list_persons

CAVITY_LETTERS = frozenset("ABCDEFGHJKLMNPQR")
DAY_START_MIN = 7 * 60 + 30
NIGHT_START_MIN = 19 * 60 + 30
TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_RULES = {
    "lim_cavity_rate_above_pct": 5.0,
    "lim_cavity_min_qty": 30.0,
    "lim_machine_rate_above_pct": 5.0,
    "lim_machine_min_qty": 30.0,
    "body_cavity_rate_above_pct": 5.0,
    "body_cavity_min_qty": 30.0,
    "body_machine_rate_above_pct": 5.0,
    "body_machine_min_qty": 30.0,
}


def _pct(value, fallback: float) -> float:
    try:
        return min(100.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return fallback


def _qty(value, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return fallback


def _first(value: dict, *keys):
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def _normalize_rules(raw: dict | None) -> dict:
    value = dict(raw) if isinstance(raw, dict) else {}
    legacy_rate = value.get("rate_above_pct")
    legacy_qty = value.get("min_qty")
    lim_cavity_rate = _first(
        value, "lim_cavity_rate_above_pct", "cavity_rate_above_pct"
    )
    if lim_cavity_rate is None:
        lim_cavity_rate = legacy_rate
    lim_cavity_qty = _first(value, "lim_cavity_min_qty", "cavity_min_qty")
    if lim_cavity_qty is None:
        lim_cavity_qty = legacy_qty
    lim_machine_rate = _first(
        value, "lim_machine_rate_above_pct", "machine_rate_above_pct"
    )
    if lim_machine_rate is None:
        lim_machine_rate = legacy_rate
    lim_machine_qty = _first(value, "lim_machine_min_qty", "machine_min_qty")
    if lim_machine_qty is None:
        lim_machine_qty = legacy_qty

    lim_cavity_rate = _pct(
        lim_cavity_rate, DEFAULT_RULES["lim_cavity_rate_above_pct"]
    )
    lim_cavity_qty = _qty(lim_cavity_qty, DEFAULT_RULES["lim_cavity_min_qty"])
    lim_machine_rate = _pct(
        lim_machine_rate, DEFAULT_RULES["lim_machine_rate_above_pct"]
    )
    lim_machine_qty = _qty(lim_machine_qty, DEFAULT_RULES["lim_machine_min_qty"])

    body_cavity_rate = _first(value, "body_cavity_rate_above_pct")
    if body_cavity_rate is None:
        body_cavity_rate = lim_cavity_rate
    body_cavity_qty = _first(value, "body_cavity_min_qty")
    if body_cavity_qty is None:
        body_cavity_qty = lim_cavity_qty
    body_machine_rate = _first(value, "body_machine_rate_above_pct")
    if body_machine_rate is None:
        body_machine_rate = lim_machine_rate
    body_machine_qty = _first(value, "body_machine_min_qty")
    if body_machine_qty is None:
        body_machine_qty = lim_machine_qty

    rules = {
        "lim_cavity_rate_above_pct": lim_cavity_rate,
        "lim_cavity_min_qty": lim_cavity_qty,
        "lim_machine_rate_above_pct": lim_machine_rate,
        "lim_machine_min_qty": lim_machine_qty,
        "body_cavity_rate_above_pct": _pct(
            body_cavity_rate, DEFAULT_RULES["body_cavity_rate_above_pct"]
        ),
        "body_cavity_min_qty": _qty(
            body_cavity_qty, DEFAULT_RULES["body_cavity_min_qty"]
        ),
        "body_machine_rate_above_pct": _pct(
            body_machine_rate, DEFAULT_RULES["body_machine_rate_above_pct"]
        ),
        "body_machine_min_qty": _qty(
            body_machine_qty, DEFAULT_RULES["body_machine_min_qty"]
        ),
    }
    rules["cavity_rate_above_pct"] = rules["lim_cavity_rate_above_pct"]
    rules["cavity_min_qty"] = rules["lim_cavity_min_qty"]
    rules["machine_rate_above_pct"] = rules["lim_machine_rate_above_pct"]
    rules["machine_min_qty"] = rules["lim_machine_min_qty"]
    rules["rate_above_pct"] = rules["lim_machine_rate_above_pct"]
    rules["min_qty"] = rules["lim_machine_min_qty"]
    return rules


def _session():
    init_meta_store()
    return MetaSession()


def load_alert_rules() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, CAVITY_ALERT_RULES_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        return _normalize_rules(value)
    finally:
        db.close()


def save_alert_rules(data: dict) -> dict:
    rules = _normalize_rules(data)
    db = _session()
    try:
        row = db.get(MetaSetting, CAVITY_ALERT_RULES_KEY)
        if row is None:
            db.add(MetaSetting(key=CAVITY_ALERT_RULES_KEY, value=rules))
        else:
            row.value = rules
        db.commit()
        return rules
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cavity_letter(cavity: str) -> str:
    text = str(cavity or "").strip().upper()
    match = re.search(r"([A-Z])\s*$", text)
    letter = match.group(1) if match else ""
    return letter if letter in CAVITY_LETTERS else ""


def current_duty(now: datetime | None = None) -> str:
    stamp = now.astimezone(TZ) if now else datetime.now(TZ)
    minutes = stamp.hour * 60 + stamp.minute
    if DAY_START_MIN <= minutes < NIGHT_START_MIN:
        return "白班"
    return "夜班"


def _rate_pct(qty: float, ng: float) -> float | None:
    if qty <= 0:
        return None
    return round((ng / qty) * 100, 2)


def _is_alert(rate_pct: float | None, qty: float, *, rate_above: float, min_qty: float) -> bool:
    if rate_pct is None:
        return False
    if qty < min_qty:
        return False
    return rate_pct >= rate_above


def _phone_for(entry: dict, persons: list[dict]) -> str:
    direct = str(entry.get("phone") or "").strip()
    if direct:
        return direct
    pid = entry.get("person_id")
    if pid is not None:
        for person in persons:
            if person.get("id") == pid:
                phone = str(person.get("phone") or "").strip()
                if phone:
                    return phone
    name = str(entry.get("name") or "").strip()
    for person in persons:
        if person.get("name") == name:
            return str(person.get("phone") or "").strip()
    return ""


def list_yield_alerts(
    project_id: str | None = None,
    *,
    hours: int = 3,
) -> dict:
    all_projects, _chosen = _enabled_project(None)
    projects = all_projects
    if project_id:
        projects = [p for p in all_projects if p.get("project_id") == project_id]
        if not projects:
            raise ValueError("项目不存在")
    project_list = [
        {"project_id": p["project_id"], "display_name": p["display_name"]}
        for p in all_projects
    ]
    duty = current_duty()
    rules = load_alert_rules()
    empty = {
        "projects": project_list,
        "current": None,
        "ready": False,
        "duty": duty,
        "hours": hours,
        "from_hour": "",
        "to_hour": "",
        "rules": rules,
        "alerts": [],
        "notices": [],
    }
    if not projects:
        return empty

    roster = list_roster()
    persons = list_persons()
    entries = roster.get("entries") or []
    alerts = []
    notice_map: dict[tuple[str, str], dict] = {}
    ready_any = False
    from_hour = ""
    to_hour = ""
    used_hours = hours

    for project in projects:
        display_name = str(project.get("display_name") or project["project_id"])
        try:
            cavity = query_machine_cavity_breakdown(project["project_id"], hours=hours)
            ready_any = True
        except ValueError:
            continue
        used_hours = cavity.get("hours") or hours
        from_hour = cavity.get("from_hour") or from_hour
        to_hour = cavity.get("to_hour") or to_hour

        red_rows = []
        machine_tot: dict[str, dict[str, float]] = {}
        for row in cavity.get("rows") or []:
            machine = str(row.get("machine") or "").strip()
            letter = _cavity_letter(str(row.get("cavity") or ""))
            if not machine or not letter:
                continue
            qty = float(row.get("qty") or 0)
            ng = float(row.get("ng") or 0)
            rate = row.get("rate_pct")
            if rate is None:
                rate = _rate_pct(qty, ng)
            prev = machine_tot.get(machine) or {"qty": 0.0, "ng": 0.0}
            machine_tot[machine] = {
                "qty": prev["qty"] + qty,
                "ng": prev["ng"] + ng,
            }
            if not _is_alert(
                rate,
                qty,
                rate_above=rules["lim_cavity_rate_above_pct"],
                min_qty=rules["lim_cavity_min_qty"],
            ):
                continue
            red_rows.append(
                {
                    **row,
                    "machine": machine,
                    "cavity_letter": letter,
                    "qty": qty,
                    "ng": ng,
                    "rate_pct": rate,
                }
            )

        contacts_of: dict[str, list[dict]] = {}
        for machine in sorted(
            {item["machine"] for item in red_rows},
            key=lambda m: (len(m), m),
        ):
            tot = machine_tot.get(machine) or {"qty": 0.0, "ng": 0.0}
            qty = tot["qty"]
            ng = tot["ng"]
            rate = _rate_pct(qty, ng)
            contacts = []
            seen = set()
            machine_payload = {
                "project_id": project["project_id"],
                "project_name": display_name,
                "machine": machine,
                "qty": qty,
                "ng": ng,
                "rate_pct": rate,
            }
            for entry in entries:
                if str(entry.get("duty") or "") != duty:
                    continue
                machines = [str(m).strip() for m in (entry.get("machines") or [])]
                if machine not in machines:
                    continue
                name = str(entry.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                phone = _phone_for(entry, persons)
                person_id = entry.get("person_id")
                contacts.append(
                    {
                        "person_id": person_id,
                        "name": name,
                        "phone": phone,
                    }
                )
                key = (name, phone)
                notice = notice_map.setdefault(
                    key,
                    {
                        "name": name,
                        "phone": phone,
                        "person_id": person_id,
                        "duty": duty,
                        "machines": [],
                    },
                )
                notice["machines"].append(dict(machine_payload))
            contacts_of[machine] = contacts

        red_rows.sort(
            key=lambda item: (
                item.get("machine") or "",
                item.get("cavity_letter") or "",
            )
        )
        for item in red_rows:
            machine = item["machine"]
            tot = machine_tot.get(machine) or {"qty": 0.0, "ng": 0.0}
            defects = [
                defect
                for defect in (item.get("defects") or [])
                if str(defect.get("item") or "").strip() not in _APPEARANCE_ITEMS
                and str(defect.get("label") or "").strip()
                not in _APPEARANCE_ITEMS
            ]
            alerts.append(
                {
                    "project_id": project["project_id"],
                    "project_name": display_name,
                    "machine": machine,
                    "cavity": item.get("cavity_letter") or "",
                    "cavity_raw": str(item.get("cavity") or ""),
                    "qty": float(item.get("qty") or 0),
                    "ng": float(item.get("ng") or 0),
                    "rate_pct": item.get("rate_pct"),
                    "reasons": [
                        str(d.get("label") or d.get("item") or "")
                        for d in defects
                    ],
                    "defects": defects,
                    "machine_qty": tot["qty"],
                    "machine_ng": tot["ng"],
                    "machine_rate_pct": _rate_pct(tot["qty"], tot["ng"]),
                    "contacts": contacts_of.get(machine) or [],
                }
            )

    alerts.sort(
        key=lambda row: (
            row["project_name"],
            len(row["machine"]),
            row["machine"],
            row.get("cavity") or "",
        )
    )
    notices = sorted(notice_map.values(), key=lambda n: n["name"])
    return {
        "projects": project_list,
        "current": None,
        "ready": ready_any,
        "duty": duty,
        "hours": used_hours,
        "from_hour": from_hour,
        "to_hour": to_hour,
        "rules": rules,
        "alerts": alerts,
        "notices": notices,
    }
