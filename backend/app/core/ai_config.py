"""AI 模型连接配置（OpenAI 兼容接口，密钥加密存 meta_settings）。"""

from __future__ import annotations

from app.core.db import MetaSession
from app.core.meta_init import AI_MODEL_KEY, DEFAULT_AI_MODEL, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.secret_box import decrypt_text, encrypt_text


def _session():
    init_meta_store()
    return MetaSession()


def _merge_stored(stored: dict | None) -> dict:
    base = dict(DEFAULT_AI_MODEL)
    if isinstance(stored, dict):
        for key in DEFAULT_AI_MODEL:
            if key in stored and stored[key] is not None:
                base[key] = stored[key]
    return base


def load_ai_config_raw() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, AI_MODEL_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
        return _merge_stored(stored)
    finally:
        db.close()


def get_ai_api_key() -> str:
    raw = load_ai_config_raw()
    return decrypt_text(str(raw.get("api_key_enc") or ""))


def load_ai_config_public() -> dict:
    raw = load_ai_config_raw()
    return {
        "enabled": bool(raw.get("enabled")),
        "provider": str(raw.get("provider") or "openai_compatible"),
        "base_url": str(raw.get("base_url") or DEFAULT_AI_MODEL["base_url"]),
        "model": str(raw.get("model") or DEFAULT_AI_MODEL["model"]),
        "timeout_seconds": int(raw.get("timeout_seconds") or 45),
        "temperature": float(raw.get("temperature") or 0.2),
        "api_key_set": bool(raw.get("api_key_enc")),
        "ready": bool(raw.get("enabled"))
        and bool(str(raw.get("base_url") or "").strip())
        and bool(str(raw.get("model") or "").strip())
        and bool(raw.get("api_key_enc")),
    }


def save_ai_config(data: dict) -> dict:
    current = load_ai_config_raw()
    if "enabled" in data and data["enabled"] is not None:
        current["enabled"] = bool(data["enabled"])
    if "provider" in data and data["provider"] is not None:
        current["provider"] = str(data["provider"] or "openai_compatible").strip()
    if "base_url" in data and data["base_url"] is not None:
        current["base_url"] = str(data["base_url"] or "").strip().rstrip("/")
    if "model" in data and data["model"] is not None:
        current["model"] = str(data["model"] or "").strip()
    if "timeout_seconds" in data and data["timeout_seconds"] is not None:
        current["timeout_seconds"] = max(5, min(180, int(data["timeout_seconds"])))
    if "temperature" in data and data["temperature"] is not None:
        current["temperature"] = max(0.0, min(2.0, float(data["temperature"])))
    if "api_key" in data and data["api_key"] is not None:
        key = str(data["api_key"]).strip()
        if key:
            current["api_key_enc"] = encrypt_text(key)
        # 空字符串表示不改密钥；显式 clear_api_key 才清空
    if data.get("clear_api_key"):
        current["api_key_enc"] = ""

    db = _session()
    try:
        row = db.get(MetaSetting, AI_MODEL_KEY)
        if row is None:
            db.add(MetaSetting(key=AI_MODEL_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        return load_ai_config_public()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
