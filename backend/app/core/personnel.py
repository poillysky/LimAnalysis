from sqlalchemy import select

from app.core.db import MetaSession
from app.core.meta_init import DEFAULT_PERSONNEL_OPTIONS, PERSONNEL_OPTIONS_KEY
from app.core.meta_models import MetaPerson, MetaSetting


def _session():
    from app.core.meta_init import init_meta_store

    init_meta_store()
    return MetaSession()


def _to_dict(row: MetaPerson) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "phone": row.phone,
        "shift": row.shift,
        "department": row.department,
    }


def _clean_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("请填写姓名")
    if len(value) > 50:
        raise ValueError("姓名过长")
    return value


def load_personnel_options() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, PERSONNEL_OPTIONS_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        shifts = value.get("shifts") or DEFAULT_PERSONNEL_OPTIONS["shifts"]
        departments = value.get("departments") or DEFAULT_PERSONNEL_OPTIONS["departments"]
        return {
            "shifts": [str(item) for item in shifts],
            "departments": [str(item) for item in departments],
        }
    finally:
        db.close()


def list_persons() -> list[dict]:
    db = _session()
    try:
        rows = db.scalars(
            select(MetaPerson).order_by(MetaPerson.department, MetaPerson.name)
        ).all()
        return [_to_dict(row) for row in rows]
    finally:
        db.close()


def get_person(person_id: int) -> dict | None:
    db = _session()
    try:
        row = db.get(MetaPerson, person_id)
        return _to_dict(row) if row else None
    finally:
        db.close()


def create_person(data: dict) -> dict:
    db = _session()
    try:
        row = MetaPerson(
            name=_clean_name(str(data.get("name") or "")),
            phone=str(data.get("phone") or "").strip(),
            shift=str(data.get("shift") or "").strip(),
            department=str(data.get("department") or "").strip(),
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


def update_person(person_id: int, data: dict) -> dict:
    db = _session()
    try:
        row = db.get(MetaPerson, person_id)
        if row is None:
            raise LookupError("人员不存在")
        if "name" in data and data["name"] is not None:
            row.name = _clean_name(str(data["name"]))
        if "phone" in data and data["phone"] is not None:
            row.phone = str(data["phone"]).strip()
        if "shift" in data and data["shift"] is not None:
            row.shift = str(data["shift"]).strip()
        if "department" in data and data["department"] is not None:
            row.department = str(data["department"]).strip()
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


def delete_person(person_id: int) -> None:
    db = _session()
    try:
        row = db.get(MetaPerson, person_id)
        if row is None:
            raise LookupError("人员不存在")
        db.delete(row)
        db.commit()
    except LookupError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
