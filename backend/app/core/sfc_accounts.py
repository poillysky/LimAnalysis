from datetime import datetime

from sqlalchemy import select

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaSfcAccount
from app.core.secret_box import decrypt_text, encrypt_text


def _session():
    init_meta_store()
    return MetaSession()


def _to_public(row: MetaSfcAccount) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "username": row.username,
        "sort_order": row.sort_order,
        "enabled": bool(row.enabled),
        "password_set": bool(row.password_enc),
        "total_use_count": row.total_use_count,
        "success_count": row.success_count,
        "failed_count": row.failed_count,
        "last_use_time": row.last_use_time,
        "last_use_status": row.last_use_status,
        "last_error": row.last_error,
    }


def list_accounts() -> list[dict]:
    db = _session()
    try:
        rows = db.scalars(
            select(MetaSfcAccount).order_by(MetaSfcAccount.sort_order, MetaSfcAccount.id)
        ).all()
        return [_to_public(row) for row in rows]
    finally:
        db.close()


def enabled_accounts_with_password() -> list[dict]:
    db = _session()
    try:
        rows = db.scalars(
            select(MetaSfcAccount)
            .where(MetaSfcAccount.enabled.is_(True))
            .order_by(MetaSfcAccount.sort_order, MetaSfcAccount.id)
        ).all()
        return [
            {
                **_to_public(row),
                "password": decrypt_text(row.password_enc),
            }
            for row in rows
        ]
    finally:
        db.close()


def create_account(data: dict) -> dict:
    username = str(data.get("username") or "").strip()
    if not username:
        raise ValueError("请填写用户名")
    password = str(data.get("password") or "")
    if not password:
        raise ValueError("请填写密码")
    db = _session()
    try:
        row = MetaSfcAccount(
            name=str(data.get("name") or username).strip(),
            username=username,
            password_enc=encrypt_text(password),
            sort_order=int(data.get("sort_order") or 0),
            enabled=bool(data.get("enabled", True)),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_public(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_account(account_id: int, data: dict) -> dict | None:
    db = _session()
    try:
        row = db.get(MetaSfcAccount, account_id)
        if row is None:
            return None
        if "name" in data and data["name"] is not None:
            row.name = str(data["name"]).strip()
        if "username" in data and data["username"] is not None:
            username = str(data["username"]).strip()
            if not username:
                raise ValueError("请填写用户名")
            row.username = username
        if data.get("password"):
            row.password_enc = encrypt_text(str(data["password"]))
        if "sort_order" in data and data["sort_order"] is not None:
            row.sort_order = int(data["sort_order"])
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = bool(data["enabled"])
        db.commit()
        db.refresh(row)
        return _to_public(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_account(account_id: int) -> bool:
    db = _session()
    try:
        row = db.get(MetaSfcAccount, account_id)
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_account(account_id: int, success: bool, error: str = "") -> None:
    db = _session()
    try:
        row = db.get(MetaSfcAccount, account_id)
        if row is None:
            return
        row.total_use_count += 1
        row.last_use_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if success:
            row.success_count += 1
            row.last_use_status = "success"
            row.last_error = ""
        else:
            row.failed_count += 1
            row.last_use_status = "failed"
            row.last_error = error[:500]
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
