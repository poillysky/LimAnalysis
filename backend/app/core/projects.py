import re

from sqlalchemy import select

from app.core.column_map import normalize_column_map
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


def _normalize_appearance_machines(raw) -> list[str]:
    """外观机自由列表（不走注塑线号目录）。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        code = str(item).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code[:80])
    return out


# 兼容旧引用；可选视角名现从项目聚合度量字段读取
DEFAULT_APPEARANCE_VIEWS = (
    "外长直边",
    "正面硅胶",
    "内长直边",
    "反面烟囱",
    "正面支架",
    "反面边框",
    "硅胶短边",
)


def _normalize_appearance_views(raw) -> list[str]:
    """已勾选的视角/分项名；未登记为空。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name[:80])
    return out


def appearance_view_names(project: dict | None) -> frozenset[str]:
    """项目已登记视角名；未登记返回空（不做排除）。"""
    if not isinstance(project, dict):
        return frozenset()
    return frozenset(_normalize_appearance_views(project.get("appearance_views")))


def _measure_item_name(target_field: str) -> str | None:
    """度量 `xxx不良数` → `xxx`；总不良 / 非不良数列忽略。"""
    name = str(target_field or "").strip()
    if not name.endswith("不良数") or "总不良" in name:
        return None
    item = name[: -len("不良数")].strip()
    return item or None


def list_appearance_view_options(project_id: str) -> list[str]:
    """从项目聚合模型的度量字段取可选名（*不良数，去掉后缀）。"""
    from sqlalchemy import select

    from app.core.meta_models import MetaAggModel, MetaAggModelField

    pid = str(project_id or "").strip()
    if not pid:
        return []
    db = _session()
    try:
        model = db.scalars(
            select(MetaAggModel).where(MetaAggModel.project_id == pid)
        ).first()
        if model is None:
            return []
        rows = db.scalars(
            select(MetaAggModelField)
            .where(MetaAggModelField.model_id == model.id)
            .order_by(MetaAggModelField.sort_order, MetaAggModelField.id)
        ).all()
        seen: set[str] = set()
        out: list[str] = []
        for row in rows:
            if str(row.field_category or "").strip() != "measure":
                continue
            item = _measure_item_name(str(row.target_field or ""))
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out
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
            "appearance_machines": _normalize_appearance_machines(
                (row.config or {}).get("appearance_machines")
            ),
            "appearance_views": _normalize_appearance_views(
                (row.config or {}).get("appearance_views")
            ),
            "owners": _normalize_owners((row.config or {}).get("owners")),
            "column_map": normalize_column_map(
                (row.config or {}).get("column_map")
            ),
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
    """兼容旧配置：曾把单个负责人写成标量而非列表。"""
    if raw is None or raw == "":
        return []
    if isinstance(raw, (int, float)):
        raw = [raw]
    elif isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple, set)):
        return []
    seen: set[int] = set()
    out: list[int] = []
    for item in raw:
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
    if "appearance_machines" in data and data["appearance_machines"] is not None:
        config["appearance_machines"] = _normalize_appearance_machines(
            data["appearance_machines"]
        )
    else:
        config["appearance_machines"] = _normalize_appearance_machines(
            config.get("appearance_machines") or []
        )
    if "appearance_views" in data and data["appearance_views"] is not None:
        config["appearance_views"] = _normalize_appearance_views(
            data["appearance_views"]
        )
    else:
        config["appearance_views"] = _normalize_appearance_views(
            config.get("appearance_views") or []
        )
    if "owners" in data and data["owners"] is not None:
        config["owners"] = _normalize_owners(data["owners"])
    else:
        config["owners"] = _normalize_owners(config.get("owners"))
    if "column_map" in data and data["column_map"] is not None:
        config["column_map"] = normalize_column_map(data["column_map"])
    elif "column_map" in config:
        config["column_map"] = normalize_column_map(config.get("column_map"))
    else:
        config["column_map"] = []
    return config


def resolve_sfc_code(
    *,
    display_name: str = "",
    prefix: str = "",
    project_id: str = "",
    current: str = "",
) -> str:
    """下载 p 参数：空或等于显示名时补成 SFC{DisplayName}（已带 SFC 则原样）。"""
    name = str(display_name or prefix or project_id).strip()
    code = str(current or "").strip()
    if code and code != name:
        return code
    if not name:
        return code
    return name if name.upper().startswith("SFC") else f"SFC{name}"


def resolve_btype(current: str | None = None) -> str:
    """下载 type 参数：空则 0。"""
    return str(current or "").strip() or "0"


def _auto_sfc_code(row: MetaProject) -> None:
    row.sfc_code = resolve_sfc_code(
        display_name=row.display_name or "",
        prefix=row.prefix or "",
        project_id=row.project_id or "",
        current=row.sfc_code or "",
    )
    row.btype = resolve_btype(row.btype)


def _fill_sfc_defaults(row: MetaProject) -> bool:
    before_code, before_type = row.sfc_code, row.btype
    _auto_sfc_code(row)
    return row.sfc_code != before_code or row.btype != before_type


def load_projects() -> list[dict]:
    defaults = load_system_defaults()
    db = _session()
    try:
        rows = db.scalars(select(MetaProject).order_by(MetaProject.project_id)).all()
        filled = False
        for row in rows:
            if _fill_sfc_defaults(row):
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
        if _fill_sfc_defaults(row):
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
        row = MetaProject(
            project_id=project_id,
            display_name=display_name,
            enabled=bool(data.get("enabled", True)),
            sfc_code=str(data.get("sfc_code") or "").strip(),
            btype=resolve_btype(data.get("btype")),
            prefix=prefix,
            config=_merge_project_config(data),
        )
        _auto_sfc_code(row)
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
            old_name = str(row.display_name or "").strip()
            row.display_name = str(data["display_name"]).strip()
            # 改名时：仅当 code 仍是空/旧自动值，才跟显示名重算
            if "sfc_code" not in data:
                current = str(row.sfc_code or "").strip()
                old_auto = resolve_sfc_code(
                    display_name=old_name,
                    prefix=row.prefix or "",
                    project_id=row.project_id or "",
                )
                if not current or current in (old_name, old_auto):
                    row.sfc_code = ""
        if "enabled" in data and data["enabled"] is not None:
            row.enabled = bool(data["enabled"])
        if "sfc_code" in data and data["sfc_code"] is not None:
            row.sfc_code = str(data["sfc_code"]).strip()
        if "btype" in data and data["btype"] is not None:
            row.btype = resolve_btype(data["btype"])
        if "prefix" in data and data["prefix"] is not None:
            row.prefix = str(data["prefix"])
        _auto_sfc_code(row)
        if (
            ("config" in data and data["config"] is not None)
            or ("machines" in data and data["machines"] is not None)
            or ("appearance_machines" in data and data["appearance_machines"] is not None)
            or ("appearance_views" in data and data["appearance_views"] is not None)
            or ("owners" in data and data["owners"] is not None)
            or ("appearance_folder" in data and data["appearance_folder"] is not None)
            or ("column_map" in data and data["column_map"] is not None)
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
    """删除项目。NAS 多容器共写 SQLite 时遇 database is locked 会短重试。"""
    import time

    from sqlalchemy.exc import OperationalError

    last_exc: Exception | None = None
    for attempt in range(4):
        db = _session()
        try:
            row = db.get(MetaProject, project_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True
        except OperationalError as exc:
            db.rollback()
            last_exc = exc
            # 锁冲突：让出后重试（外观索引/采集写 meta 时常见）
            if attempt < 3 and "locked" in str(exc).lower():
                time.sleep(0.35 * (attempt + 1))
                continue
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    if last_exc:
        raise last_exc
    return False
