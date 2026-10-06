import hashlib
import hmac
import os
import re

from sqlalchemy import func, select

from app.core.db import MetaSession
from app.core.meta_models import MetaUser

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{2,50}$")
_ROLES = {"admin", "common"}
_PBKDF2_ROUNDS = 120_000


def _session():
    from app.core.meta_init import init_meta_store

    init_meta_store()
    return MetaSession()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS
    )
    return hmac.compare_digest(actual, expected)


def _to_dict(row: MetaUser) -> dict:
    return {
        "username": row.username,
        "nickname": row.nickname,
        "role": row.role,
        "enabled": row.enabled,
    }


def _validate_username(username: str) -> str:
    name = username.strip()
    if not _USERNAME_RE.fullmatch(name):
        raise ValueError("账号须为 2～50 位字母、数字或下划线")
    return name


def _validate_role(role: str) -> str:
    value = (role or "common").strip()
    if value not in _ROLES:
        raise ValueError("角色只能是 admin 或 common")
    return value


def _count_enabled_admins(db, exclude_username: str | None = None) -> int:
    stmt = select(func.count()).select_from(MetaUser).where(
        MetaUser.role == "admin", MetaUser.enabled.is_(True)
    )
    if exclude_username:
        stmt = stmt.where(MetaUser.username != exclude_username)
    return int(db.scalar(stmt) or 0)


def seed_default_admin() -> None:
    db = MetaSession()
    try:
        if db.scalar(select(func.count()).select_from(MetaUser)):
            return
        db.add(
            MetaUser(
                username="admin",
                nickname="管理员",
                password_hash=hash_password("admin123"),
                role="admin",
                enabled=True,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_users() -> list[dict]:
    db = _session()
    try:
        rows = db.scalars(select(MetaUser).order_by(MetaUser.username)).all()
        return [_to_dict(row) for row in rows]
    finally:
        db.close()


def get_user(username: str) -> dict | None:
    db = _session()
    try:
        row = db.get(MetaUser, username)
        return _to_dict(row) if row else None
    finally:
        db.close()


def authenticate(username: str, password: str) -> dict:
    name = username.strip()
    db = _session()
    try:
        row = db.get(MetaUser, name)
        if row is None or not row.enabled or not verify_password(password, row.password_hash):
            raise PermissionError("账号或密码错误")
        return _to_dict(row)
    finally:
        db.close()


def create_user(data: dict) -> dict:
    username = _validate_username(str(data.get("username") or ""))
    password = str(data.get("password") or "")
    if len(password) < 6:
        raise ValueError("密码至少 6 位")
    role = _validate_role(str(data.get("role") or "common"))
    db = _session()
    try:
        if db.get(MetaUser, username):
            raise ValueError("账号已存在")
        row = MetaUser(
            username=username,
            nickname=str(data.get("nickname") or username).strip(),
            password_hash=hash_password(password),
            role=role,
            enabled=bool(data.get("enabled", True)),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_dict(row)
    except ValueError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_user(username: str, data: dict) -> dict:
    db = _session()
    try:
        row = db.get(MetaUser, username)
        if row is None:
            raise LookupError("用户不存在")
        if "nickname" in data and data["nickname"] is not None:
            row.nickname = str(data["nickname"]).strip() or row.username
        if "role" in data and data["role"] is not None:
            new_role = _validate_role(str(data["role"]))
            if (
                row.role == "admin"
                and new_role != "admin"
                and _count_enabled_admins(db, exclude_username=row.username) < 1
                and row.enabled
            ):
                raise ValueError("至少保留一名启用中的管理员")
            row.role = new_role
        if "enabled" in data and data["enabled"] is not None:
            enabled = bool(data["enabled"])
            if (
                row.role == "admin"
                and row.enabled
                and not enabled
                and _count_enabled_admins(db, exclude_username=row.username) < 1
            ):
                raise ValueError("至少保留一名启用中的管理员")
            row.enabled = enabled
        if data.get("password"):
            password = str(data["password"])
            if len(password) < 6:
                raise ValueError("密码至少 6 位")
            row.password_hash = hash_password(password)
        db.commit()
        db.refresh(row)
        return _to_dict(row)
    except (ValueError, LookupError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_user(username: str) -> None:
    db = _session()
    try:
        row = db.get(MetaUser, username)
        if row is None:
            raise LookupError("用户不存在")
        if (
            row.role == "admin"
            and row.enabled
            and _count_enabled_admins(db, exclude_username=row.username) < 1
        ):
            raise ValueError("不能删除最后一名启用中的管理员")
        db.delete(row)
        db.commit()
    except (ValueError, LookupError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
