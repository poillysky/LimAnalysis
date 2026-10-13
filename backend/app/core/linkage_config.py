"""SFC → 清洗 → 聚合 联动配置（meta_settings）。

与 ETL/AGG 定时调度互斥：开启联动时关闭两侧定时。
"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import (
    DEFAULT_PIPELINE_LINKAGE,
    PIPELINE_LINKAGE_KEY,
    init_meta_store,
)
from app.core.meta_models import MetaSetting


def _session():
    init_meta_store()
    return MetaSession()


def load_linkage_config() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, PIPELINE_LINKAGE_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        merged = {**DEFAULT_PIPELINE_LINKAGE, **stored}
        merged["enabled"] = bool(merged.get("enabled"))
        merged["delay_seconds"] = max(
            1, min(3600, int(merged.get("delay_seconds") or 60))
        )
        return merged
    finally:
        db.close()


def save_linkage_config(data: dict, *, peer_sync: bool = True) -> dict:
    current = load_linkage_config()
    if "enabled" in data and data["enabled"] is not None:
        current["enabled"] = bool(data["enabled"])
    if "delay_seconds" in data and data["delay_seconds"] is not None:
        current["delay_seconds"] = max(1, min(3600, int(data["delay_seconds"])))

    db = _session()
    try:
        row = db.get(MetaSetting, PIPELINE_LINKAGE_KEY)
        if row is None:
            db.add(MetaSetting(key=PIPELINE_LINKAGE_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        result = load_linkage_config()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # 联动与定时互斥：开启联动时关闭清洗/聚合定时
    if peer_sync and result.get("enabled"):
        from app.core.agg_config import load_agg_config, save_agg_config
        from app.core.etl_config import load_etl_config, save_etl_config

        if load_etl_config().get("is_active"):
            save_etl_config({"is_active": False}, peer_sync=False)
        if load_agg_config().get("is_active"):
            save_agg_config({"is_active": False}, peer_sync=False)
    return result
