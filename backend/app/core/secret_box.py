import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.db import MetaSession
from app.core.meta_init import AUTH_SECRET_KEY, init_meta_store
from app.core.meta_models import MetaSetting


def _fernet() -> Fernet:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, AUTH_SECRET_KEY)
        secret = ""
        if row and isinstance(row.value, dict):
            secret = str(row.value.get("secret") or "")
        if not secret:
            raise RuntimeError("auth secret missing")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))
    finally:
        db.close()


def encrypt_text(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
