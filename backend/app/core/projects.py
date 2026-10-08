import re

from sqlalchemy import select

from app.core.db import MetaSession
from app.core.meta_init import (
    DEFAULT_MACHINE_CATALOG,
    MACHINE_CATALOG_KEY,
    SYSTEM_DEFAULTS_KEY,
    init_meta_store,
)
from app.core.meta_models import MetaProject, MetaSetting


def _session():
    init_meta_store()
    return MetaSession()


def load_system_defaults() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, SYSTEM_DEFAULTS_KEY)
        return dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()


def save_system_defaults(value: dict) -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, SYSTEM_DEFAULTS_KEY)
        if row is None:
            row = MetaSetting(key=SYSTEM_DEFAULTS_KEY, value=value)
            db.add(row)
        else:
            row.value = value
        db.commit()
        return dict(row.value)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _to_dict(row: MetaProject, defaults: dict) -> dict:
    item = {**defaults}
    item.update(row.config or {})
    item.update(
        {
            "project_id": row.project_id,
            "display_name": row.display_name,
            "enabled": row.enabled,
            "sfc_code": row.sfc_code,
            "btype": row.btype,
            "prefix": row.prefix,
            "machines": list((row.config or {}).get("machines") or []),
            "owners": _normalize_owners((row.config or {}).get("owners")),
        }
    )
    return item


def _slug_from_name(name: str) -> str:
    value = name.strip()
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[\s\-]+", "_", value)
    value = value.lower()
    value = re.sub(r"[^a-z0-9_]", "", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:50] or "project"


def _unique_project_id(db, base: str) -> str:
    candidate = base
    n = 2
    while db.get(MetaProject, candidate):
        suffix = f"_{n}"
        candidate = f"{base[: 50 - len(suffix)]}{suffix}"
        n += 1
        if n > 999:
            raise ValueError("无法生成唯一 project_id")
    return candidate


def load_machine_catalog() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, MACHINE_CATALOG_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
        groups = value.get("groups") or DEFAULT_MACHINE_CATALOG["groups"]
        cleaned = []
        for group in groups:
            name = str(group.get("name") or "").strip()
            raw_machines = group.get("machines") or []
            machines = [str(item).strip() for item in raw_machines if str(item).strip()]
            if name and machines:
                cleaned.append({"name": name, "machines": machines})
        return {"groups": cleaned or DEFAULT_MACHINE_CATALOG["groups"]}
    finally:
        db.close()


def _catalog_codes() -> list[str]:
    codes = []
    for group in load_machine_catalog()["groups"]:
        codes.extend(group["machines"])
    return codes


def _normalize_machines(raw) -> list[str]:
    allowed = list(_catalog_codes())
    selected = {str(item).strip() for item in (raw or []) if str(item).strip()}
    return [code for code in allowed if code in selected]


def _person_ids(raw) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item in raw or []:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in seen:
            seen.add(value)
            out.append(value)
    return out


OWNER_AREAS = ("injection", "lim", "finished")
OWNER_ROLES = ("production", "quality", "process")
OWNER_SOLO = ("structure_rd", "pm")


def empty_owners() -> dict:
    return {
        "injection": {"production": [], "quality": [], "process": []},
        "lim": {"production": [], "quality": [], "process": []},
        "finished": {"production": [], "quality": [], "process": []},
        "structure_rd": [],
        "pm": [],
    }


def _normalize_owners(raw) -> dict:
    result = empty_owners()
    if not isinstance(raw, dict):
        return result
    for area in OWNER_AREAS:
        src = raw.get(area) if isinstance(raw.get(area), dict) else {}
        for role in OWNER_ROLES:
            result[area][role] = _person_ids(src.get(role))
    for key in OWNER_SOLO:
        result[key] = _person_ids(raw.get(key))
    return result


def _merge_project_config(data: dict, existing: dict | None = None) -> dict:
    config = dict(existing or {})
    incoming = data.get("config")
    if isinstance(incoming, dict):
        config.update(incoming)
    if "appearance_folder" in data and data["appearance_folder"] is not None:
        config["appearance_folder"] = str(data["appearance_folder"]).strip()
    if "machines" in data and data["machines"] is not None:
        config["machines"] = _normalize_machines(data["machines"])
    else:
        config["machines"] = _normalize_machines(config.get("machines") or [])
    if "owners" in data and data["owners"] is not None:
        config["owners"] = _normalize_owners(data["owners"])
    else:
        config["owners"] = _normalize_owners(config.get("owners"))
    return config


def _auto_sfc_code(row: MetaProject) -> None:
    if str(row.sfc_code or "").strip():
        return
    row.sfc_code = str(row.display_name or row.prefix or row.project_id).strip()


def load_projects() -> list[dict]:
    defaults = load_system_defaults()
    db = _session()
    try:
        rows = db.scalars(select(MetaProject).order_by(MetaProject.project_id)).all()
        filled = False
        for row in rows:
            before = row.sfc_code
            _auto_sfc_code(row)
            if row.sfc_code != before:
                filled = True
        if filled:
            db.commit()
        return [_to_dict(row, defaults) for row in rows]
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_project(project_id: str) -> dict | None:
    defaults = load_system_defaults()
    db = _session()
    try:
        row = db.get(MetaProject, project_id)
        if row is None:
            return None
        before = row.sfc_code
        _auto_sfc_code(row)
        if row.sfc_code != before:
            db.commit()
        return _to_dict(row, defaults)
    finally:
        db.close()


def create_project(data: dict) -> dict:
    db = _session()
    try:
        display_name = str(data.get("display_name") or data.get("project_id") or "").strip()
        if not display_name:
            raise ValueError("请填写名称")
        requested_id = str(data.get("project_id") or "").strip()
        base_id = requested_id or _slug_from_name(display_name)
        project_id = _unique_project_id(db, base_id)
        prefix = str(data.get("prefix") or "").strip() or project_id
        sfc_code = str(data.get("sfc_code") or "").strip() or display_name
        row = MetaProject(
            project_id=project_id,
            display_name=display_name,
            enabled=bool(data.get("enabled", True)),
            sfc_code=sfc_code,
            btype=str(data.get("btype") or ""),
            prefix=prefix,
            config=_merge_project_config(data),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _to_dict(row, load_system_defaults())
    except ValueError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_project(project_id: str, data: dict) -> dict | None:
    db = _session()
    try:
        row = db.get(MetaProject, project_id)
        if row is None:
            return None
        if "display_name" in data and data["display_name"] is not None:
            row.display_name = str(data["display_name"])
            if not str(data.get("sfc_code") or row.sfc_code or "").strip():
                row.sfc_code = row.display_name
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = bool(data["enabled"])
        if "sfc_code" in data and data["sfc_code"] is not None:
            row.sfc_code = str(data["sfc_code"]).strip() or row.display_name
        _auto_sfc_code(row)
        if "btype" in data and data["btype"] is not None:
            row.btype = str(data["btype"])
        if "prefix" in data and data["prefix"] is not None:
            row.prefix = str(data["prefix"])
        if (
            ("config" in data and data["config"] is not None)
            or ("machines" in data and data["machines"] is not None)
            or ("owners" in data and data["owners"] is not None)
            or ("appearance_folder" in data and data["appearance_folder"] is not None)
        ):
            row.config = _merge_project_config(data, row.config)
        db.commit()
        db.refresh(row)
        return _to_dict(row, load_system_defaults())
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_project(project_id: str) -> bool:
    db = _session()
    try:
        row = db.get(MetaProject, project_id)
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
