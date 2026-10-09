"""车间配置（兼容旧 API；不再因 offline 限制任何功能）。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import WORKSHOP_KEY, init_meta_store
from app.core.meta_models import MetaSetting


def load_workshop_config() -> dict:
    """始终返回 offline=false，不再读取/强制 WORKSHOP_OFFLINE。"""
    return {"offline": False, "env_forced": False}


def is_workshop_offline() -> bool:
    return False


def save_workshop_config(data: dict) -> dict:
    """兼容 PUT /system/workshop：写入 meta，但运行时不再据此停功能。"""
    offline = (
        bool(data.get("offline"))
        if "offline" in data and data["offline"] is not None
        else False
    )
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, WORKSHOP_KEY)
        payload = {"offline": offline}
        if row is None:
            db.add(MetaSetting(key=WORKSHOP_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return load_workshop_config()
