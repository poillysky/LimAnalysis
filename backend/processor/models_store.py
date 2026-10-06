"""ETL link 模型与字段映射存取（SQLite meta）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect, select, text

from app.core.db import MetaSession
from app.core.meta_models import MetaEtlModel, MetaEtlModelField
from app.core.projects import load_projects, load_system_defaults
from app.core.sql_ident import ident, q
from processor.field_types import (
    FIELD_TYPES,
    guess_field_type,
    guess_field_types_for_table,
    normalize_field_type,
)
from processor.sql_generator import write_link_sql_file
from processor.validators import validate_fields


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _project_map() -> dict[str, dict]:
    return {p["project_id"]: p for p in load_projects()}


def _default_unique_key(project: dict) -> str:
    uk = project.get("unique_key") if isinstance(project.get("unique_key"), dict) else {}
    col = str((uk or {}).get("column") or "").strip()
    if col:
        return ident(col)
    defaults = load_system_defaults()
    col = str((defaults.get("unique_key") or {}).get("column") or "FCoverSN").strip()
    return ident(col or "FCoverSN")


def _tables_for_project(project: dict) -> tuple[str, str]:
    prefix = ident(str(project.get("prefix") or project.get("project_id") or ""))
    return f"{prefix}_raw", f"{prefix}_dwd"


def field_to_dict(row: MetaEtlModelField) -> dict:
    return {
        "id": row.id,
        "model_id": row.model_id,
        "source_field": row.source_field,
        "target_field": row.target_field,
        "field_type": row.field_type,
        "mapping_type": row.mapping_type,
        "derive_level": row.derive_level,
        "formula": row.formula,
        "constant_value": row.constant_value,
        "sort_order": row.sort_order,
        "is_required": row.is_required,
        "description": row.description,
    }


def model_to_dict(row: MetaEtlModel, *, include_fields: bool = False) -> dict:
    projects = _project_map()
    project = projects.get(row.project_id) or {}
    data = {
        "id": row.id,
        "project_id": row.project_id,
        "display_name": project.get("display_name") or row.name,
        "project_enabled": bool(project.get("enabled", True)),
        "name": row.name,
        "source_table": row.source_table,
        "target_table": row.target_table,
        "unique_key": row.unique_key,
        "incremental_field": row.incremental_field,
        "sql_path": row.sql_path,
        "is_enabled": bool(row.is_enabled),
        "is_draft": bool(row.is_draft),
        "field_count": 0,
        "last_run_time": row.last_run_time or "",
        "last_run_status": row.last_run_status or "",
        "last_run_rows": int(row.last_run_rows or 0),
        "last_run_message": row.last_run_message or "",
        "config": dict(row.config or {}),
        "can_run": (
            bool(row.is_enabled)
            and not bool(row.is_draft)
            and bool(row.sql_path)
            and bool(project.get("enabled", True))
        ),
    }
    cfg = dict(row.config or {})
    source_fields = list(cfg.get("source_fields") or [])
    data["source_fields"] = source_fields
    data["source_field_count"] = len(source_fields)
    if include_fields:
        fields = list_fields(row.id)
        data["fields"] = fields
        data["field_count"] = len(fields)
    else:
        db = MetaSession()
        try:
            data["field_count"] = len(
                db.scalars(
                    select(MetaEtlModelField).where(MetaEtlModelField.model_id == row.id)
                ).all()
            )
        finally:
            db.close()
    return data


def ensure_model_for_project(project_id: str) -> dict:
    """按项目懒创建草稿 link 模型。"""
    pid = str(project_id or "").strip()
    projects = _project_map()
    project = projects.get(pid)
    if project is None:
        raise ValueError("项目不存在")

    source, target = _tables_for_project(project)
    db = MetaSession()
    try:
        row = db.scalars(
            select(MetaEtlModel).where(MetaEtlModel.project_id == pid)
        ).first()
        if row is None:
            row = MetaEtlModel(
                project_id=pid,
                name=str(project.get("display_name") or pid),
                source_table=source,
                target_table=target,
                unique_key=_default_unique_key(project),
                incremental_field="",
                sql_path="",
                is_enabled=False,
                is_draft=True,
                config={},
            )
            db.add(row)
            db.commit()
            db.refresh(row)
        else:
            # 同步源/目标表名（prefix 变更时）
            changed = False
            if row.source_table != source:
                row.source_table = source
                changed = True
            if row.target_table != target:
                row.target_table = target
                changed = True
            if not row.unique_key:
                row.unique_key = _default_unique_key(project)
                changed = True
            if changed:
                db.commit()
                db.refresh(row)
        return model_to_dict(row, include_fields=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_models() -> list[dict]:
    """确保每个启用/存在的项目都有模型，返回列表。"""
    for project in load_projects():
        ensure_model_for_project(project["project_id"])
    db = MetaSession()
    try:
        rows = db.scalars(select(MetaEtlModel).order_by(MetaEtlModel.project_id)).all()
        return [model_to_dict(r) for r in rows]
    finally:
        db.close()


def get_model(model_id: int, *, include_fields: bool = True) -> dict | None:
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            return None
        return model_to_dict(row, include_fields=include_fields)
    finally:
        db.close()


def get_model_by_project(project_id: str, *, include_fields: bool = False) -> dict | None:
    ensure_model_for_project(project_id)
    db = MetaSession()
    try:
        row = db.scalars(
            select(MetaEtlModel).where(MetaEtlModel.project_id == str(project_id))
        ).first()
        if row is None:
            return None
        return model_to_dict(row, include_fields=include_fields)
    finally:
        db.close()


def update_model(model_id: int, data: dict) -> dict:
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        if "name" in data and data["name"] is not None:
            row.name = str(data["name"]).strip() or row.name
        if "unique_key" in data and data["unique_key"] is not None:
            row.unique_key = ident(str(data["unique_key"]).strip())
        if "incremental_field" in data and data["incremental_field"] is not None:
            row.incremental_field = ident(str(data["incremental_field"]).strip()) if data["incremental_field"] else ""
        if "is_enabled" in data and data["is_enabled"] is not None:
            enabled = bool(data["is_enabled"])
            if enabled and (row.is_draft or not row.sql_path):
                raise ValueError("请先保存字段映射并生成 SQL，再启用模型")
            row.is_enabled = enabled
        db.commit()
        db.refresh(row)
        return model_to_dict(row, include_fields=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_fields(model_id: int) -> list[dict]:
    db = MetaSession()
    try:
        rows = db.scalars(
            select(MetaEtlModelField)
            .where(MetaEtlModelField.model_id == int(model_id))
            .order_by(MetaEtlModelField.sort_order, MetaEtlModelField.id)
        ).all()
        return [field_to_dict(r) for r in rows]
    finally:
        db.close()


def save_fields(model_id: int, fields: list[dict]) -> dict:
    """保存字段 → 校验 → 生成 SQL → 清草稿。"""
    normalized: list[dict] = []
    for idx, item in enumerate(fields or []):
        if not isinstance(item, dict):
            continue
        mapping_type = str(item.get("mapping_type") or "direct").strip().lower()
        target = str(item.get("target_field") or "").strip()
        source = str(item.get("source_field") or "").strip()
        if mapping_type == "direct" and not source:
            source = target
        normalized.append(
            {
                "source_field": source,
                "target_field": target,
                "field_type": normalize_field_type(item.get("field_type")),
                "mapping_type": mapping_type,
                "derive_level": int(item.get("derive_level") or 1),
                "formula": str(item.get("formula") or ""),
                "constant_value": str(
                    item.get("constant_value") if item.get("constant_value") is not None else ""
                ),
                "sort_order": int(item.get("sort_order") if item.get("sort_order") is not None else idx),
                "is_required": bool(item.get("is_required")),
                "description": str(item.get("description") or "")[:500],
            }
        )

    check = validate_fields(normalized)
    if not check["valid"]:
        raise ValueError("; ".join(check["errors"][:8]))

    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")

        existing = db.scalars(
            select(MetaEtlModelField).where(MetaEtlModelField.model_id == row.id)
        ).all()
        for old in existing:
            db.delete(old)
        db.flush()

        # 用原表类型目录补全 field_type（清洗列未填时）
        cfg = dict(row.config or {})
        type_by_source = {
            str(s.get("source_field") or ""): normalize_field_type(s.get("field_type"))
            for s in (cfg.get("source_fields") or [])
            if isinstance(s, dict)
        }
        for item in normalized:
            if item["mapping_type"] == "direct" and item["source_field"] in type_by_source:
                item["field_type"] = type_by_source[item["source_field"]]
            db.add(
                MetaEtlModelField(
                    model_id=row.id,
                    source_field=item["source_field"],
                    target_field=item["target_field"],
                    field_type=item["field_type"],
                    mapping_type=item["mapping_type"],
                    derive_level=item["derive_level"],
                    formula=item["formula"],
                    constant_value=item["constant_value"],
                    sort_order=item["sort_order"],
                    is_required=item["is_required"],
                    description=item["description"],
                )
            )

        sql_text, sql_path = write_link_sql_file(
            model_name=row.name,
            source_table=row.source_table,
            target_table=row.target_table,
            fields=normalized,
            unique_key=row.unique_key,
            description=f"project={row.project_id}",
        )
        row.sql_path = sql_path
        row.is_draft = False
        db.commit()
        db.refresh(row)
        result = model_to_dict(row, include_fields=True)
        result["sql_preview"] = sql_text
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_fields(model_id: int) -> dict:
    """清空清洗表映射；可选保留原表类型目录。"""
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        existing = db.scalars(
            select(MetaEtlModelField).where(MetaEtlModelField.model_id == row.id)
        ).all()
        for old in existing:
            db.delete(old)
        row.sql_path = ""
        row.is_draft = True
        row.is_enabled = False
        db.commit()
        db.refresh(row)
        return model_to_dict(row, include_fields=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_all_config(model_id: int) -> dict:
    """清空原表类型目录 + 清洗表映射。"""
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        existing = db.scalars(
            select(MetaEtlModelField).where(MetaEtlModelField.model_id == row.id)
        ).all()
        for old in existing:
            db.delete(old)
        cfg = dict(row.config or {})
        cfg["source_fields"] = []
        row.config = cfg
        row.sql_path = ""
        row.is_draft = True
        row.is_enabled = False
        db.commit()
        db.refresh(row)
        return model_to_dict(row, include_fields=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_source_fields(model_id: int, source_fields: list[dict]) -> dict:
    """保存原表字段类型目录（不写清洗映射、不生成 SQL）。"""
    normalized: list[dict] = []
    for idx, item in enumerate(source_fields or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("source_field") or item.get("name") or "").strip()
        if not name:
            continue
        normalized.append(
            {
                "source_field": name,
                "field_type": normalize_field_type(item.get("field_type")),
                "sort_order": int(
                    item.get("sort_order") if item.get("sort_order") is not None else idx
                ),
            }
        )
    if not normalized:
        raise ValueError("原表字段为空，请先从源表导入")

    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        cfg = dict(row.config or {})
        cfg["source_fields"] = normalized
        row.config = cfg
        # 只改类型目录时保持草稿；若已有清洗映射则不删
        if not row.sql_path:
            row.is_draft = True
        db.commit()
        db.refresh(row)
        return model_to_dict(row, include_fields=True)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _sample_and_guess_source_fields(source_table: str) -> list[dict]:
    """读源表列 + 采样推断类型。"""
    from app.core import db as stores

    stores.refresh_pg_engines()
    insp = inspect(stores.raw_engine)
    if not insp.has_table(source_table):
        raise ValueError(f"原始表不存在: {source_table}（请先采集/上传）")
    columns = [c["name"] for c in insp.get_columns(source_table)]
    if not columns:
        raise ValueError("源表没有列")

    sample_rows: list = []
    try:
        col_sql = ", ".join(q(ident(c)) for c in columns)
        table_sql = q(ident(source_table))
        with stores.raw_engine.connect() as conn:
            sample_rows = list(
                conn.execute(
                    text(f"SELECT {col_sql} FROM {table_sql} LIMIT 500")
                ).mappings()
            )
    except Exception:
        sample_rows = []

    type_map = guess_field_types_for_table(columns, sample_rows)
    return [
        {
            "source_field": col,
            "field_type": type_map.get(col) or guess_field_type(col),
            "sort_order": idx,
        }
        for idx, col in enumerate(columns)
    ]


def reanalyze_source_field_types(model_id: int) -> dict:
    """按列名+采样重新推断原表字段类型；不清空清洗映射。"""
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        source_table = row.source_table
    finally:
        db.close()

    source_fields = _sample_and_guess_source_fields(source_table)

    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        cfg = dict(row.config or {})
        cfg["source_fields"] = source_fields
        row.config = cfg
        db.commit()
        db.refresh(row)
        result = model_to_dict(row, include_fields=True)
        result["field_types"] = FIELD_TYPES
        result["reanalyzed"] = True
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def import_direct_fields(model_id: int) -> dict:
    """从源表导入原始字段名 + 建议类型到 config.source_fields；清空清洗表映射。"""
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        source_table = row.source_table
    finally:
        db.close()

    source_fields = _sample_and_guess_source_fields(source_table)

    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        # 清空已有清洗表字段，避免自动带入
        existing = db.scalars(
            select(MetaEtlModelField).where(MetaEtlModelField.model_id == row.id)
        ).all()
        for old in existing:
            db.delete(old)
        cfg = dict(row.config or {})
        cfg["source_fields"] = source_fields
        row.config = cfg
        row.sql_path = ""
        row.is_draft = True
        row.is_enabled = False
        db.commit()
        db.refresh(row)
        result = model_to_dict(row, include_fields=True)
        result["field_types"] = FIELD_TYPES
        result["imported_only"] = True
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_source_columns(model_id: int) -> list[dict]:
    from app.core import db as stores

    model = get_model(model_id, include_fields=False)
    if model is None:
        raise ValueError("模型不存在")
    source = model["source_table"]
    stores.refresh_pg_engines()
    insp = inspect(stores.raw_engine)
    if not insp.has_table(source):
        return []
    cols = []
    for c in insp.get_columns(source):
        cols.append(
            {
                "column_name": c["name"],
                "column_type": str(c.get("type") or "TEXT"),
                "nullable": bool(c.get("nullable", True)),
            }
        )
    return cols


def touch_model_run(model_id: int, *, ok: bool, rows: int, message: str) -> None:
    db = MetaSession()
    try:
        row = db.get(MetaEtlModel, int(model_id))
        if row is None:
            return
        row.last_run_time = _now()
        row.last_run_status = "success" if ok else "failed"
        row.last_run_rows = int(rows)
        row.last_run_message = str(message or "")[:500]
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def assert_model_runnable(model: dict) -> None:
    if not model:
        raise ValueError("模型不存在")
    if model.get("is_draft"):
        raise ValueError("草稿模型不能执行，请先保存字段映射")
    if not model.get("sql_path"):
        raise ValueError("模型未生成 SQL，请先配置并保存字段映射")
    if not model.get("is_enabled"):
        raise ValueError("模型未启用")
    if not model.get("project_enabled", True):
        raise ValueError("项目已停用")
    if int(model.get("field_count") or 0) <= 0 and not model.get("fields"):
        raise ValueError("请先配置字段映射")
