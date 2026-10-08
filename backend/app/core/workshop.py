"""车间模式：离线值守时停外网调度、限制 AI。"""

from __future__ import annotations

from app.core.config import settings
from app.core.db import MetaSession
from app.core.meta_init import DEFAULT_WORKSHOP, WORKSHOP_KEY, init_meta_store
from app.core.meta_models import MetaSetting


def _merge(stored: dict | None) -> dict:
    base = dict(DEFAULT_WORKSHOP)
    if isinstance(stored, dict):
        for key in DEFAULT_WORKSHOP:
            if key in stored and stored[key] is not None:
                base[key] = stored[key]
    return base


def _load_meta_workshop() -> dict:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, WORKSHOP_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        return _merge(stored)
    finally:
        db.close()


def load_workshop_config() -> dict:
    cfg = _load_meta_workshop()
    # .env 可强制开启（车间部署脚本默认），meta 里也可改
    if settings.workshop_offline:
        cfg["offline"] = True
    cfg["env_forced"] = bool(settings.workshop_offline)
    return cfg


def is_workshop_offline() -> bool:
    return bool(load_workshop_config().get("offline"))


def save_workshop_config(data: dict) -> dict:
    current = _load_meta_workshop()
    if "offline" in data and data["offline"] is not None:
        current["offline"] = bool(data["offline"])
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, WORKSHOP_KEY)
        payload = {"offline": bool(current["offline"])}
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
