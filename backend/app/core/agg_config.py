"""ADS 自动聚合调度配置（meta_settings）。

与 pipeline_linkage 互斥：开启定时运行时会关闭联动。
"""

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
        merged["mode"] = "interval"
        # 旧配置可能只有 hourly、无 run_interval → 默认 60 分钟
        merged["run_interval"] = max(
            1, min(24 * 60, int(merged.get("run_interval") or 60))
        )
        merged["backfill_hours"] = AUTO_BACKFILL_HOURS
        return merged
    finally:
        db.close()


def save_agg_config(data: dict, *, peer_sync: bool = True) -> dict:
    current = load_agg_config()
    if "is_active" in data and data["is_active"] is not None:
        current["is_active"] = bool(data["is_active"])
    if "run_interval" in data and data["run_interval"] is not None:
        current["run_interval"] = max(1, min(24 * 60, int(data["run_interval"])))
    current["mode"] = "interval"
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
        result = load_agg_config()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # 定时运行与联动互斥：开启定时时关闭联动
    if peer_sync and result.get("is_active"):
        from app.core.linkage_config import load_linkage_config, save_linkage_config

        if load_linkage_config().get("enabled"):
            save_linkage_config({"enabled": False}, peer_sync=False)
    return result


def patch_agg_config(data: dict) -> dict:
    return save_agg_config(data)
