"""排班表：白班 / 夜班 · 人员 · 负责机台。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import DUTY_ROSTER_KEY, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.personnel import get_person, list_persons
from app.core.projects import load_machine_catalog

DUTIES = ("白班", "夜班")


def _session():
    init_meta_store()
    return MetaSession()


def _machine_codes() -> list[str]:
    codes: list[str] = []
    for group in load_machine_catalog().get("groups") or []:
        for code in group.get("machines") or []:
            text = str(code).strip()
            if text and text not in codes:
                codes.append(text)
    return codes


def _normalize_machines(raw) -> list[str]:
    selected = []
    seen = set()
    for item in raw or []:
        code = str(item).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        selected.append(code)
    return selected


def _load_raw() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, DUTY_ROSTER_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        entries = value.get("entries") if isinstance(value.get("entries"), list) else []
        return {"entries": entries}
    finally:
        db.close()


def _save_raw(entries: list[dict]) -> list[dict]:
    db = _session()
    try:
        payload = {"entries": entries}
        row = db.get(MetaSetting, DUTY_ROSTER_KEY)
        if row is None:
            db.add(MetaSetting(key=DUTY_ROSTER_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        return entries
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _next_id(entries: list[dict]) -> int:
    nums = []
    for item in entries:
        try:
            nums.append(int(item.get("id")))
        except (TypeError, ValueError):
            continue
    return (max(nums) + 1) if nums else 1


def _to_entry(raw: dict) -> dict | None:
    try:
        eid = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    duty = str(raw.get("duty") or "").strip()
    if duty not in DUTIES:
        return None
    person_id = raw.get("person_id")
    try:
        person_id = int(person_id) if person_id is not None else None
    except (TypeError, ValueError):
        person_id = None
    name = str(raw.get("name") or "").strip()
    phone = str(raw.get("phone") or "").strip()
    if person_id is not None:
        person = get_person(person_id)
        if person:
            name = person["name"]
            phone = str(person.get("phone") or "").strip()
    if not name:
        return None
    return {
        "id": eid,
        "person_id": person_id,
        "name": name,
        "phone": phone,
        "duty": duty,
        "machines": _normalize_machines(raw.get("machines")),
    }


def list_roster() -> dict:
    raw = _load_raw()
    entries = []
    for item in raw["entries"]:
        if not isinstance(item, dict):
            continue
        entry = _to_entry(item)
        if entry:
            entries.append(entry)
    duty_rank = {d: i for i, d in enumerate(DUTIES)}
    entries.sort(
        key=lambda e: (duty_rank.get(e["duty"], 99), e["name"], e["id"])
    )
    return {
        "entries": entries,
        "duties": list(DUTIES),
        "machines": _machine_codes(),
        "persons": [
            {
                "id": p["id"],
                "name": p["name"],
                "phone": p.get("phone") or "",
                "department": p.get("department") or "",
            }
            for p in list_persons()
        ],
    }


def create_roster_entry(data: dict) -> dict:
    duty = str(data.get("duty") or "").strip()
    if duty not in DUTIES:
        raise ValueError("请选择白班或夜班")
    person_id = data.get("person_id")
    try:
        person_id = int(person_id) if person_id is not None else None
    except (TypeError, ValueError):
        person_id = None
    name = str(data.get("name") or "").strip()
    if person_id is not None:
        person = get_person(person_id)
        if person is None:
            raise ValueError("人员不存在")
        name = person["name"]
    if not name:
        raise ValueError("请选择人员")
    machines = _normalize_machines(data.get("machines"))
    if not machines:
        raise ValueError("请至少选择一台负责机台")

    raw = _load_raw()
    entries = [e for e in raw["entries"] if isinstance(e, dict)]
    entry = {
        "id": _next_id(entries),
        "person_id": person_id,
        "name": name,
        "duty": duty,
        "machines": machines,
    }
    entries.append(entry)
    _save_raw(entries)
    return entry


def update_roster_entry(entry_id: int, data: dict) -> dict:
    raw = _load_raw()
    entries = [e for e in raw["entries"] if isinstance(e, dict)]
    target = None
    for item in entries:
        try:
            if int(item.get("id")) == entry_id:
                target = item
                break
        except (TypeError, ValueError):
            continue
    if target is None:
        raise LookupError("排班记录不存在")

    if "duty" in data and data["duty"] is not None:
        duty = str(data["duty"]).strip()
        if duty not in DUTIES:
            raise ValueError("请选择白班或夜班")
        target["duty"] = duty

    if "person_id" in data:
        person_id = data.get("person_id")
        try:
            person_id = int(person_id) if person_id is not None else None
        except (TypeError, ValueError):
            person_id = None
        if person_id is not None:
            person = get_person(person_id)
            if person is None:
                raise ValueError("人员不存在")
            target["person_id"] = person_id
            target["name"] = person["name"]
        elif data.get("name"):
            target["person_id"] = None
            target["name"] = str(data["name"]).strip()

    if "name" in data and data["name"] is not None and target.get("person_id") is None:
        name = str(data["name"]).strip()
        if not name:
            raise ValueError("请填写人员姓名")
        target["name"] = name

    if "machines" in data and data["machines"] is not None:
        machines = _normalize_machines(data["machines"])
        if not machines:
            raise ValueError("请至少选择一台负责机台")
        target["machines"] = machines

    cleaned = _to_entry(target)
    if cleaned is None:
        raise ValueError("排班数据无效")
    for i, item in enumerate(entries):
        try:
            if int(item.get("id")) == entry_id:
                entries[i] = cleaned
                break
        except (TypeError, ValueError):
            continue
    _save_raw(entries)
    return cleaned


def delete_roster_entry(entry_id: int) -> None:
    raw = _load_raw()
    entries = []
    found = False
    for item in raw["entries"]:
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("id")) == entry_id:
                found = True
                continue
        except (TypeError, ValueError):
            pass
        entries.append(item)
    if not found:
        raise LookupError("排班记录不存在")
    _save_raw(entries)
