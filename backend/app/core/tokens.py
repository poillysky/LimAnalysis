import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

from app.core.db import MetaSession
from app.core.meta_init import AUTH_SECRET_KEY, init_meta_store
from app.core.meta_models import MetaSetting

ACCESS_HOURS = 12
REFRESH_DAYS = 7
# <img src> 无法带 Authorization，图片 URL 用短时签名票据自证身份
MEDIA_HOURS = 12

_secret_cache: bytes | None = None


def _secret() -> bytes:
    """读取鉴权密钥；进程内缓存，避免批量签发图片票据时反复打 meta。"""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSetting, AUTH_SECRET_KEY)
        value = row.value if row and isinstance(row.value, dict) else {}
        secret = str(value.get("secret") or "")
        if not secret:
            raise RuntimeError("auth secret missing")
        _secret_cache = secret.encode("utf-8")
        return _secret_cache
    finally:
        db.close()


def clear_secret_cache() -> None:
    """测试用：清空密钥缓存。"""
    global _secret_cache
    _secret_cache = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def issue_token(username: str, kind: str, lifetime: timedelta) -> tuple[str, datetime]:
    expires = datetime.now() + lifetime
    payload = {
        "u": username,
        "t": kind,
        "exp": int(expires.timestamp()),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}", expires


def parse_token(token: str, kind: str) -> str:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise PermissionError("登录已失效") from exc
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    actual = _b64url_decode(sig)
    if not hmac.compare_digest(expected, actual):
        raise PermissionError("登录已失效")
    try:
        payload = json.loads(_b64url_decode(body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise PermissionError("登录已失效") from exc
    if payload.get("t") != kind:
        raise PermissionError("登录已失效")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise PermissionError("登录已失效")
    username = str(payload.get("u") or "")
    if not username:
        raise PermissionError("登录已失效")
    return username


def issue_session(user: dict) -> dict:
    access, access_exp = issue_token(
        user["username"], "access", timedelta(hours=ACCESS_HOURS)
    )
    refresh, _ = issue_token(user["username"], "refresh", timedelta(days=REFRESH_DAYS))
    role = user["role"]
    return {
        "avatar": "",
        "username": user["username"],
        "nickname": user["nickname"],
        "roles": [role],
        "permissions": ["*:*:*"] if role == "admin" else [],
        "accessToken": access,
        "refreshToken": refresh,
        "expires": access_exp.strftime("%Y/%m/%d %H:%M:%S"),
    }


def issue_media_ticket(
    source: str, rel: str, *, lifetime: timedelta | None = None
) -> str:
    """签发绑定到具体图片路径的短时票据，供 <img src> 使用。"""
    src = str(source or "").strip() or "mold"
    path = str(rel or "").replace("\\", "/").strip()
    if not path:
        raise ValueError("图片路径无效")
    expires = datetime.now() + (lifetime or timedelta(hours=MEDIA_HOURS))
    payload = {
        "t": "media",
        "s": src,
        "r": path,
        "exp": int(expires.timestamp()),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def parse_media_ticket(ticket: str) -> tuple[str, str]:
    """校验图片票据，返回 (source, rel)。"""
    text = str(ticket or "").strip()
    if not text:
        raise PermissionError("缺少图片凭证")
    try:
        body, sig = text.split(".", 1)
    except ValueError as exc:
        raise PermissionError("图片凭证无效") from exc
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    actual = _b64url_decode(sig)
    if not hmac.compare_digest(expected, actual):
        raise PermissionError("图片凭证无效")
    try:
        payload = json.loads(_b64url_decode(body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise PermissionError("图片凭证无效") from exc
    if payload.get("t") != "media":
        raise PermissionError("图片凭证无效")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise PermissionError("图片凭证已过期")
    source = str(payload.get("s") or "").strip()
    rel = str(payload.get("r") or "").replace("\\", "/").strip()
    if not source or not rel:
        raise PermissionError("图片凭证无效")
    return source, rel
