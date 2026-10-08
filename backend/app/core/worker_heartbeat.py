"""Worker 进程心跳：写入 meta，供 runtime-status 判断进程是否存活。"""

from __future__ import annotations

import os
import time
from datetime import datetime

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaSetting

WORKER_HEARTBEAT_KEY = "worker_heartbeat"
STALE_SECONDS = 45
_ROLES = ("collector", "agg")
_TIME_FMT = "%Y-%m-%d %H:%M:%S"

# 进程内节流，避免每秒写 SQLite
_last_touch_mono: dict[str, float] = {}
_TOUCH_MIN_INTERVAL = 10.0


def _now_str() -> str:
    return datetime.now().strftime(_TIME_FMT)


def touch_worker_heartbeat(role: str, *, force: bool = False) -> None:
    """更新某角色心跳。默认至少间隔 10s；启动时可用 force=True。"""
    if role not in _ROLES:
        return
    mono = time.monotonic()
    if not force and mono - _last_touch_mono.get(role, 0.0) < _TOUCH_MIN_INTERVAL:
        return
    _last_touch_mono[role] = mono

    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, WORKER_HEARTBEAT_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        stored[role] = {
            "at": _now_str(),
            "pid": os.getpid(),
        }
        if row is None:
            db.add(MetaSetting(key=WORKER_HEARTBEAT_KEY, value=stored))
        else:
            row.value = stored
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _parse_at(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _TIME_FMT)
    except ValueError:
        return None


def worker_heartbeat_status(*, stale_seconds: int = STALE_SECONDS) -> dict:
    """返回 collector / agg 的存活摘要。"""
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, WORKER_HEARTBEAT_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()

    now = datetime.now()
    out: dict[str, dict] = {}
    for role in _ROLES:
        entry = stored.get(role) if isinstance(stored.get(role), dict) else {}
        at = str(entry.get("at") or "")
        ts = _parse_at(at)
        age = int((now - ts).total_seconds()) if ts else None
        alive = age is not None and age <= stale_seconds
        out[role] = {
            "alive": alive,
            "last_seen": at,
            "age_seconds": age,
            "pid": entry.get("pid"),
            "stale_after_seconds": stale_seconds,
        }
    return out
