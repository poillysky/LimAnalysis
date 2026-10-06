from app.core.db import MetaSession
from app.core.meta_init import DEFAULT_SFC_CRAWLER, SFC_CRAWLER_KEY, init_meta_store
from app.core.meta_models import MetaSetting


def _session():
    init_meta_store()
    return MetaSession()


def load_sfc_config() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, SFC_CRAWLER_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        merged = {**DEFAULT_SFC_CRAWLER, **stored}
        return merged
    finally:
        db.close()


def save_sfc_config(data: dict) -> dict:
    current = load_sfc_config()
    for key in DEFAULT_SFC_CRAWLER:
        if key in data and data[key] is not None:
            current[key] = data[key]
    db = _session()
    try:
        row = db.get(MetaSetting, SFC_CRAWLER_KEY)
        if row is None:
            db.add(MetaSetting(key=SFC_CRAWLER_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        return current
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def patch_sfc_config(data: dict) -> dict:
    return save_sfc_config(data)
