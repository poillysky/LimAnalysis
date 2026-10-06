"""ETL 自动清洗调度配置（meta_settings）。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import DEFAULT_ETL_SCHEDULER, ETL_SCHEDULER_KEY, init_meta_store
from app.core.meta_models import MetaSetting


def _session():
    init_meta_store()
    return MetaSession()


def load_etl_config() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, ETL_SCHEDULER_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        merged = {**DEFAULT_ETL_SCHEDULER, **stored}
        merged["is_active"] = bool(merged.get("is_active"))
        merged["run_interval"] = max(1, min(24 * 60, int(merged.get("run_interval") or 30)))
        return merged
    finally:
        db.close()


def save_etl_config(data: dict) -> dict:
    current = load_etl_config()
    if "is_active" in data and data["is_active"] is not None:
        current["is_active"] = bool(data["is_active"])
    if "run_interval" in data and data["run_interval"] is not None:
        current["run_interval"] = max(1, min(24 * 60, int(data["run_interval"])))
    if "last_run_time" in data and data["last_run_time"] is not None:
        current["last_run_time"] = str(data["last_run_time"] or "")
    if "last_run_status" in data and data["last_run_status"] is not None:
        current["last_run_status"] = str(data["last_run_status"] or "")[:40]
    if "last_run_message" in data and data["last_run_message"] is not None:
        current["last_run_message"] = str(data["last_run_message"] or "")[:500]

    db = _session()
    try:
        row = db.get(MetaSetting, ETL_SCHEDULER_KEY)
        if row is None:
            db.add(MetaSetting(key=ETL_SCHEDULER_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        return load_etl_config()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def patch_etl_config(data: dict) -> dict:
    return save_etl_config(data)
