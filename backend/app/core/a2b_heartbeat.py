"""A2BCopyTray 客户端心跳：接收入库 + 与项目槽位合并出监控状态。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaA2bClientHeartbeat
from app.core.projects import load_projects

STALE_SECONDS = 90
# 外观机固定两工站；前端一机一卡、每卡两盏监控灯
APPEARANCE_STATIONS = ("1", "2")
_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_MODES = frozenset({"mold", "appearance"})


def _session():
    init_meta_store()
    return MetaSession()


def _now_str() -> str:
    return datetime.now().strftime(_TIME_FMT)


def _parse_at(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in (_TIME_FMT, "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _str(data: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in data and data[key] is not None:
            value = str(data[key]).strip()
            if value:
                return value
    return default


def _int(data: dict, *keys: str, default: int = 0) -> int:
    for key in keys:
        if key not in data or data[key] is None:
            continue
        try:
            return int(data[key])
        except (TypeError, ValueError):
            continue
    return default


def _bool(data: dict, *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return default


def _norm_mode(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text in _MODES:
        return text
    if text in ("注塑", "注塑机", "molding"):
        return "mold"
    if text in ("外观", "外观机"):
        return "appearance"
    return text


def normalize_heartbeat_payload(data: dict | None) -> dict:
    """解析 A2B camelCase / 兼容字段，返回规范化字典。缺 client_id 时返回空 dict。"""
    raw = data if isinstance(data, dict) else {}
    alias = _str(raw, "deviceAlias", "device_alias", "clientId", "client_id")
    machine = _str(raw, "machine", "machine_name", "machineName", "deviceAlias", "clientId")
    if not machine:
        machine = alias
    client_id = alias or machine
    if not client_id:
        return {}

    mode = _norm_mode(_str(raw, "mode"))
    mode_label = _str(raw, "modeLabel", "mode_label")
    if not mode_label:
        mode_label = "外观机" if mode == "appearance" else ("注塑机" if mode == "mold" else "")

    return {
        "client_id": client_id[:120],
        "mode": mode[:20],
        "mode_label": mode_label[:40],
        "machine": machine[:80],
        "project": _str(raw, "project", "project_name", "projectName")[:80],
        "station": _str(raw, "station")[:20],
        "client_status": _str(
            raw, "clientStatus", "client_status", "status", "state", default="监控中"
        )[:40],
        "paused": _bool(raw, "paused"),
        "ok_count": _int(raw, "okCount", "ok_count"),
        "fail_count": _int(raw, "failCount", "fail_count"),
        "total_runs": _int(raw, "totalRuns", "total_runs"),
        "last_sync": _str(raw, "lastSync", "last_sync")[:40],
        "source": _str(raw, "source", "sourceDir", "source_dir")[:500],
        "target": _str(raw, "target", "targetDir", "target_dir")[:500],
        "host_name": _str(raw, "hostName", "host_name", "hostname", "host")[:120],
        "client_version": _str(
            raw, "clientVersion", "client_version", "version"
        )[:40],
        "timestamp": _str(raw, "timestamp"),
    }


def upsert_heartbeat(data: dict | None) -> dict | None:
    """写入/更新一条心跳。返回规范化行；缺标识时返回 None。"""
    norm = normalize_heartbeat_payload(data)
    if not norm:
        return None

    seen = _now_str()
    # 客户端 timestamp 仅作参考；在线判定以服务端 last_seen_at 为准
    db = _session()
    try:
        row = db.get(MetaA2bClientHeartbeat, norm["client_id"])
        if row is None:
            row = MetaA2bClientHeartbeat(client_id=norm["client_id"])
            db.add(row)
        row.mode = norm["mode"]
        row.mode_label = norm["mode_label"]
        row.machine = norm["machine"]
        row.project = norm["project"]
        row.station = norm["station"]
        row.client_status = norm["client_status"]
        row.paused = bool(norm["paused"])
        row.ok_count = int(norm["ok_count"])
        row.fail_count = int(norm["fail_count"])
        row.total_runs = int(norm["total_runs"])
        row.last_sync = norm["last_sync"]
        row.source = norm["source"]
        row.target = norm["target"]
        row.host_name = norm["host_name"]
        row.client_version = norm["client_version"]
        row.last_seen_at = seen
        row.payload = {
            "timestamp": norm["timestamp"],
            "received_at": seen,
        }
        db.commit()
        return heartbeat_to_dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def heartbeat_to_dict(row: MetaA2bClientHeartbeat) -> dict:
    return {
        "client_id": row.client_id or "",
        "mode": row.mode or "",
        "mode_label": row.mode_label or "",
        "machine": row.machine or "",
        "project": row.project or "",
        "station": row.station or "",
        "client_status": row.client_status or "",
        "paused": bool(row.paused),
        "ok_count": int(row.ok_count or 0),
        "fail_count": int(row.fail_count or 0),
        "total_runs": int(row.total_runs or 0),
        "last_sync": row.last_sync or "",
        "source": row.source or "",
        "target": row.target or "",
        "host_name": row.host_name or "",
        "client_version": row.client_version or "",
        "last_seen_at": row.last_seen_at or "",
    }


def list_heartbeats(*, mode: str | None = None) -> list[dict]:
    db = _session()
    try:
        stmt = select(MetaA2bClientHeartbeat).order_by(MetaA2bClientHeartbeat.client_id)
        rows = db.scalars(stmt).all()
        out = [heartbeat_to_dict(row) for row in rows]
    finally:
        db.close()
    if mode:
        want = _norm_mode(mode)
        out = [item for item in out if _norm_mode(item.get("mode") or "") == want]
    return out


def _presence(last_seen_at: str, *, stale_seconds: int, now: datetime | None = None) -> dict:
    """online | offline | never"""
    ts = _parse_at(last_seen_at)
    if ts is None:
        return {
            "presence": "never",
            "online": False,
            "age_seconds": None,
            "last_seen_at": last_seen_at or "",
        }
    clock = now or datetime.now()
    age = max(0, int((clock - ts).total_seconds()))
    online = age <= stale_seconds
    return {
        "presence": "online" if online else "offline",
        "online": online,
        "age_seconds": age,
        "last_seen_at": last_seen_at or "",
    }


def _eq_ci(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _project_matches(hb_project: str, project: dict) -> bool:
    text = (hb_project or "").strip()
    if not text:
        return False
    candidates = [
        str(project.get("project_id") or ""),
        str(project.get("display_name") or ""),
        str(project.get("prefix") or ""),
    ]
    return any(_eq_ci(text, c) for c in candidates if c.strip())


def _attach_heartbeat(slot: dict, hb: dict | None, *, stale_seconds: int, now: datetime) -> dict:
    base = dict(slot)
    if hb is None:
        base.update(
            {
                "registered": True,
                "presence": "never",
                "online": False,
                "age_seconds": None,
                "last_seen_at": "",
                "client_id": "",
                "client_status": "",
                "paused": False,
                "ok_count": 0,
                "fail_count": 0,
                "total_runs": 0,
                "last_sync": "",
                "source": "",
                "target": "",
                "host_name": "",
                "client_version": "",
                "mode_label": "",
            }
        )
        return base

    presence = _presence(hb.get("last_seen_at") or "", stale_seconds=stale_seconds, now=now)
    base.update(
        {
            "registered": True,
            **presence,
            "client_id": hb.get("client_id") or "",
            "client_status": hb.get("client_status") or "",
            "paused": bool(hb.get("paused")),
            "ok_count": int(hb.get("ok_count") or 0),
            "fail_count": int(hb.get("fail_count") or 0),
            "total_runs": int(hb.get("total_runs") or 0),
            "last_sync": hb.get("last_sync") or "",
            "source": hb.get("source") or "",
            "target": hb.get("target") or "",
            "host_name": hb.get("host_name") or "",
            "client_version": hb.get("client_version") or "",
            "mode_label": hb.get("mode_label") or "",
            "hb_project": hb.get("project") or "",
            "hb_machine": hb.get("machine") or "",
            "hb_station": hb.get("station") or "",
        }
    )
    return base


def _match_mold(hb: dict, machine: str) -> bool:
    if _norm_mode(hb.get("mode") or "") not in ("", "mold"):
        return False
    return _eq_ci(hb.get("machine") or "", machine) or _eq_ci(
        hb.get("client_id") or "", machine
    )


def _match_appearance(hb: dict, project: dict, machine: str, station: str) -> bool:
    if _norm_mode(hb.get("mode") or "") != "appearance":
        return False
    if not _project_matches(str(hb.get("project") or ""), project):
        return False
    if not _eq_ci(hb.get("machine") or "", machine):
        return False
    return _eq_ci(hb.get("station") or "", station)


def build_a2b_status(
    *,
    mode: str,
    stale_seconds: int = STALE_SECONDS,
    projects: list[dict] | None = None,
    heartbeats: list[dict] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """合并项目配置槽位 ∪ 心跳表。"""
    want = _norm_mode(mode)
    if want not in _MODES:
        raise ValueError("mode 须为 mold 或 appearance")
    clock = now or datetime.now()
    timeout = max(10, int(stale_seconds))
    proj_list = projects if projects is not None else load_projects()
    hb_list = heartbeats if heartbeats is not None else list_heartbeats()
    mode_hbs = [
        hb
        for hb in hb_list
        if _norm_mode(hb.get("mode") or "") == want
        or (want == "mold" and not _norm_mode(hb.get("mode") or ""))
    ]

    slots: list[dict] = []
    matched_ids: set[str] = set()

    enabled = [p for p in proj_list if p.get("enabled", True)]

    if want == "mold":
        for project in enabled:
            for machine in project.get("machines") or []:
                code = str(machine).strip()
                if not code:
                    continue
                hit = next((hb for hb in mode_hbs if _match_mold(hb, code)), None)
                if hit:
                    matched_ids.add(hit["client_id"])
                slots.append(
                    _attach_heartbeat(
                        {
                            "slot_key": f"mold:{project.get('project_id')}:{code}",
                            "mode": "mold",
                            "project_id": project.get("project_id") or "",
                            "project_name": project.get("display_name") or "",
                            "machine": code,
                            "station": "",
                            "title": code,
                        },
                        hit,
                        stale_seconds=timeout,
                        now=clock,
                    )
                )
    else:
        for project in enabled:
            machines = project.get("appearance_machines") or []
            for machine in machines:
                code = str(machine).strip()
                if not code:
                    continue
                for station in APPEARANCE_STATIONS:
                    hit = next(
                        (
                            hb
                            for hb in mode_hbs
                            if _match_appearance(hb, project, code, station)
                        ),
                        None,
                    )
                    if hit:
                        matched_ids.add(hit["client_id"])
                    title = f"{code}-工站{station}"
                    slots.append(
                        _attach_heartbeat(
                            {
                                "slot_key": (
                                    f"appearance:{project.get('project_id')}:"
                                    f"{code}:{station}"
                                ),
                                "mode": "appearance",
                                "project_id": project.get("project_id") or "",
                                "project_name": project.get("display_name") or "",
                                "machine": code,
                                "station": station,
                                "title": title,
                            },
                            hit,
                            stale_seconds=timeout,
                            now=clock,
                        )
                    )

    # 未登记区只展示仍在线的心跳；离线后卡片直接消失（正式槽位的离线/从未仍保留）
    unregistered: list[dict] = []
    for hb in mode_hbs:
        cid = hb.get("client_id") or ""
        if cid in matched_ids:
            continue
        presence = _presence(
            hb.get("last_seen_at") or "", stale_seconds=timeout, now=clock
        )
        if presence.get("presence") != "online":
            continue
        unregistered.append(
            {
                "slot_key": f"unreg:{cid}",
                "mode": want,
                "registered": False,
                "project_id": "",
                "project_name": hb.get("project") or "",
                "machine": hb.get("machine") or "",
                "station": hb.get("station") or "",
                "title": cid or hb.get("machine") or "未知",
                "client_id": cid,
                "client_status": hb.get("client_status") or "",
                "paused": bool(hb.get("paused")),
                "ok_count": int(hb.get("ok_count") or 0),
                "fail_count": int(hb.get("fail_count") or 0),
                "total_runs": int(hb.get("total_runs") or 0),
                "last_sync": hb.get("last_sync") or "",
                "source": hb.get("source") or "",
                "target": hb.get("target") or "",
                "host_name": hb.get("host_name") or "",
                "client_version": hb.get("client_version") or "",
                "mode_label": hb.get("mode_label") or "",
                **presence,
            }
        )

    summary = {
        "online": sum(1 for s in slots if s.get("presence") == "online"),
        "offline": sum(1 for s in slots if s.get("presence") == "offline"),
        "never": sum(1 for s in slots if s.get("presence") == "never"),
        "unregistered": len(unregistered),
        "total_slots": len(slots),
    }
    return {
        "mode": want,
        "stale_seconds": timeout,
        "summary": summary,
        "slots": slots,
        "unregistered": unregistered,
    }
