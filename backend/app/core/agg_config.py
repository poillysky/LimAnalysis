"""ADS 自动聚合调度配置（meta_settings）。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import AGG_SCHEDULER_KEY, DEFAULT_AGG_SCHEDULER, init_meta_store
from app.core.meta_models import MetaSetting

AUTO_BACKFILL_HOURS = 12


def _session():
    init_meta_store()
    return MetaSession()


def load_agg_config() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, AGG_SCHEDULER_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        merged = {**DEFAULT_AGG_SCHEDULER, **stored}
        merged["is_active"] = bool(merged.get("is_active"))
        merged["mode"] = "hourly"
        merged["backfill_hours"] = AUTO_BACKFILL_HOURS
        return merged
    finally:
        db.close()


def save_agg_config(data: dict) -> dict:
    current = load_agg_config()
    if "is_active" in data and data["is_active"] is not None:
        current["is_active"] = bool(data["is_active"])
    current["mode"] = "hourly"
    current["backfill_hours"] = AUTO_BACKFILL_HOURS
    if "last_run_time" in data and data["last_run_time"] is not None:
        current["last_run_time"] = str(data["last_run_time"] or "")
    if "last_run_status" in data and data["last_run_status"] is not None:
        current["last_run_status"] = str(data["last_run_status"] or "")[:40]
    if "last_run_message" in data and data["last_run_message"] is not None:
        current["last_run_message"] = str(data["last_run_message"] or "")[:500]

    db = _session()
    try:
        row = db.get(MetaSetting, AGG_SCHEDULER_KEY)
        if row is None:
            db.add(MetaSetting(key=AGG_SCHEDULER_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        return load_agg_config()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def patch_agg_config(data: dict) -> dict:
    return save_agg_config(data)
