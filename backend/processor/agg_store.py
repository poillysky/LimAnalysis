"""ADS 聚合模型存取（SQLite meta）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect, select

from app.core.db import MetaSession
from app.core.meta_models import MetaAggModel, MetaAggModelField
from app.core.projects import load_projects
from app.core.sql_ident import ident
from processor.sql_generator import write_analysis_sql_file
from processor.validators import validate_agg_fields, validate_agg_model

_TIME_CANDIDATES = ("ServerTime", "server_time", "etl_at")
_NG_CANDIDATES = ("外观总结果", "排次总结果")
_INIT_DIMENSIONS = ("自动外观线体", "机台", "模穴", "模仁", "本体")


def _init_field(
    *,
    source_field: str,
    target_field: str,
    field_category: str,
    field_type: str = "text",
    aggregate_func: str = "",
    derive_level: int = 1,
    formula: str = "",
    sort_order: int = 0,
    description: str = "",
) -> dict:
    return {
        "source_field": source_field,
        "target_field": target_field,
        "field_type": field_type,
        "field_category": field_category,
        "aggregate_func": aggregate_func,
        "derive_level": derive_level,
        "formula": formula,
        "sort_order": sort_order,
        "description": description,
    }


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _project_map() -> dict[str, dict]:
    return {p["project_id"]: p for p in load_projects()}


def _tables_for_project(project: dict) -> tuple[str, str]:
    prefix = ident(str(project.get("prefix") or project.get("project_id") or ""))
    return f"{prefix}_dwd", f"{prefix}_ads"


def field_to_dict(row: MetaAggModelField) -> dict:
    return {
        "id": row.id,
        "model_id": row.model_id,
        "source_field": row.source_field,
        "target_field": row.target_field,
        "field_type": row.field_type,
        "field_category": row.field_category,
        "aggregate_func": row.aggregate_func,
        "derive_level": row.derive_level,
        "formula": row.formula,
        "sort_order": row.sort_order,
        "description": row.description,
    }


def model_to_dict(row: MetaAggModel, *, include_fields: bool = False) -> dict:
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
        "time_field": row.time_field,
        "granularity": row.granularity,
        "time_field_name": row.time_field_name,
        "lookback_hours": int(row.lookback_hours or 1),
        "backfill_hours": int(row.backfill_hours or 12),
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
    if include_fields:
        fields = list_fields(row.id)
        data["fields"] = fields
        data["field_count"] = len(fields)
    else:
        db = MetaSession()
        try:
            data["field_count"] = len(
                db.scalars(
                    select(MetaAggModelField).where(MetaAggModelField.model_id == row.id)
                ).all()
            )
        finally:
            db.close()
    return data


def ensure_model_for_project(project_id: str) -> dict:
    pid = str(project_id or "").strip()
    projects = _project_map()
    project = projects.get(pid)
    if project is None:
        raise ValueError("项目不存在")

    source, target = _tables_for_project(project)
    db = MetaSession()
    try:
        row = db.scalars(select(MetaAggModel).where(MetaAggModel.project_id == pid)).first()
        if row is None:
            row = MetaAggModel(
                project_id=pid,
                name=str(project.get("display_name") or pid),
                source_table=source,
                target_table=target,
                time_field="ServerTime",
                granularity="hour",
                time_field_name="hour",
                lookback_hours=1,
                backfill_hours=12,
                sql_path="",
                is_enabled=False,
                is_draft=True,
                config={},
            )
            db.add(row)
            db.commit()
            db.refresh(row)
        else:
            changed = False
            if row.source_table != source:
                row.source_table = source
                changed = True
            if row.target_table != target:
                row.target_table = target
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
    for project in load_projects():
        ensure_model_for_project(project["project_id"])
    db = MetaSession()
    try:
        rows = db.scalars(select(MetaAggModel).order_by(MetaAggModel.project_id)).all()
        return [model_to_dict(r) for r in rows]
    finally:
        db.close()


def get_model(model_id: int, *, include_fields: bool = True) -> dict | None:
    db = MetaSession()
    try:
        row = db.get(MetaAggModel, int(model_id))
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
            select(MetaAggModel).where(MetaAggModel.project_id == str(project_id))
        ).first()
        if row is None:
            return None
        return model_to_dict(row, include_fields=include_fields)
    finally:
        db.close()


def update_model(model_id: int, data: dict) -> dict:
    db = MetaSession()
    try:
        row = db.get(MetaAggModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        if "name" in data and data["name"] is not None:
            row.name = str(data["name"]).strip() or row.name
        if "time_field" in data and data["time_field"] is not None:
            row.time_field = ident(str(data["time_field"]).strip()) or row.time_field
        if "granularity" in data and data["granularity"] is not None:
            grain = str(data["granularity"]).strip().lower() or "hour"
            row.granularity = grain
            if not data.get("time_field_name"):
                row.time_field_name = grain
        if "time_field_name" in data and data["time_field_name"] is not None:
            name = ident(str(data["time_field_name"]).strip())
            if name:
                row.time_field_name = name
        if "lookback_hours" in data and data["lookback_hours"] is not None:
            row.lookback_hours = max(1, min(24 * 14, int(data["lookback_hours"])))
        if "backfill_hours" in data and data["backfill_hours"] is not None:
            row.backfill_hours = max(1, min(24 * 30, int(data["backfill_hours"])))
        if "is_enabled" in data and data["is_enabled"] is not None:
            enabled = bool(data["is_enabled"])
            if enabled and (row.is_draft or not row.sql_path):
                raise ValueError("请先保存聚合配置并生成 SQL，再启用")
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
            select(MetaAggModelField)
            .where(MetaAggModelField.model_id == int(model_id))
            .order_by(MetaAggModelField.sort_order, MetaAggModelField.id)
        ).all()
        return [field_to_dict(r) for r in rows]
    finally:
        db.close()


def _normalize_fields(fields: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for idx, item in enumerate(fields or []):
        if not isinstance(item, dict):
            continue
        category = str(item.get("field_category") or "dimension").strip().lower()
        target = str(item.get("target_field") or "").strip()
        source = str(item.get("source_field") or "").strip()
        if category == "dimension" and not source:
            source = target
        if category == "measure" and not source:
            source = "*"
        func = str(item.get("aggregate_func") or "").strip().upper()
        if category == "measure" and not func:
            func = "COUNT"
        if category != "measure":
            func = ""
        level = 2 if category == "derived" else 1
        normalized.append(
            {
                "source_field": source,
                "target_field": target,
                "field_type": str(item.get("field_type") or "text"),
                "field_category": category,
                "aggregate_func": func,
                "derive_level": int(item.get("derive_level") or level),
                "formula": str(item.get("formula") or ""),
                "sort_order": int(item.get("sort_order") if item.get("sort_order") is not None else idx),
                "description": str(item.get("description") or "")[:500],
            }
        )
    return normalized


def save_model_config(model_id: int, data: dict) -> dict:
    """保存时间窗 + 字段，生成 layer2 SQL，清草稿。"""
    fields = _normalize_fields(data.get("fields") or [])
    check_fields = validate_agg_fields(fields)
    if not check_fields["valid"]:
        raise ValueError("; ".join(check_fields["errors"][:8]))

    db = MetaSession()
    try:
        row = db.get(MetaAggModel, int(model_id))
        if row is None:
            raise ValueError("模型不存在")
        if data.get("time_field"):
            row.time_field = ident(str(data["time_field"]).strip()) or row.time_field
        if data.get("granularity"):
            grain = str(data["granularity"]).strip().lower()
            row.granularity = grain
            row.time_field_name = ident(str(data.get("time_field_name") or grain))
        elif data.get("time_field_name"):
            row.time_field_name = ident(str(data["time_field_name"]).strip())
        if data.get("lookback_hours") is not None:
            row.lookback_hours = max(1, min(24 * 14, int(data["lookback_hours"])))
        if data.get("backfill_hours") is not None:
            row.backfill_hours = max(1, min(24 * 30, int(data["backfill_hours"])))

        meta_check = validate_agg_model(
            {
                "time_field": row.time_field,
                "granularity": row.granularity,
                "lookback_hours": row.lookback_hours,
                "backfill_hours": row.backfill_hours,
            }
        )
        if not meta_check["valid"]:
            raise ValueError("; ".join(meta_check["errors"][:8]))

        existing = db.scalars(
            select(MetaAggModelField).where(MetaAggModelField.model_id == row.id)
        ).all()
        for old in existing:
            db.delete(old)
        db.flush()
        for item in fields:
            db.add(
                MetaAggModelField(
                    model_id=row.id,
                    source_field=item["source_field"],
                    target_field=item["target_field"],
                    field_type=item["field_type"],
                    field_category=item["field_category"],
                    aggregate_func=item["aggregate_func"],
                    derive_level=item["derive_level"],
                    formula=item["formula"],
                    sort_order=item["sort_order"],
                    description=item["description"],
                )
            )

        sql_text, sql_path = write_analysis_sql_file(
            model_name=row.name,
            source_table=row.source_table,
            target_table=row.target_table,
            time_field=row.time_field,
            granularity=row.granularity,
            time_field_name=row.time_field_name,
            fields=fields,
            description=f"project={row.project_id}",
        )
        row.sql_path = sql_path
        row.is_draft = False
        if data.get("is_enabled") is not None:
            row.is_enabled = bool(data["is_enabled"])
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


def list_dwd_columns(model_id: int) -> list[dict]:
    """清洗表可选列：优先用数据清洗配置的目标列名，再补库里多出来的列。"""
    from app.core import db as stores
    from processor.models_store import get_model_by_project as get_etl_by_project

    model = get_model(model_id, include_fields=False)
    if model is None:
        raise ValueError("模型不存在")
    source = model["source_table"]
    seen: set[str] = set()
    cols: list[dict] = []

    etl = get_etl_by_project(str(model.get("project_id") or ""), include_fields=True)
    for item in (etl or {}).get("fields") or []:
        name = str(item.get("target_field") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cols.append(
            {
                "column_name": name,
                "column_type": str(item.get("field_type") or "TEXT"),
                "nullable": True,
            }
        )

    stores.refresh_pg_engines()
    insp = inspect(stores.dwh_engine)
    if insp.has_table(source):
        for c in insp.get_columns(source):
            name = str(c.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cols.append(
                {
                    "column_name": name,
                    "column_type": str(c.get("type") or "TEXT"),
                    "nullable": bool(c.get("nullable", True)),
                }
            )
    return cols


def suggest_fields(model_id: int) -> dict:
    """初始化字段：五维 + 注塑机总产量/总不良数 + 自动外观总产量/总不良数。不含派生不良率。"""
    model = get_model(model_id, include_fields=True)
    if model is None:
        raise ValueError("模型不存在")
    columns = [c["column_name"] for c in list_dwd_columns(model_id)]
    colset = {c: c for c in columns}
    lower = {c.lower(): c for c in columns}

    def pick(*names: str) -> str | None:
        for name in names:
            if name in colset:
                return name
            found = lower.get(name.lower())
            if found:
                return found
        return None

    time_field = pick(*_TIME_CANDIDATES) or (columns[0] if columns else "ServerTime")
    fields: list[dict] = []
    order = 0
    for name in _INIT_DIMENSIONS:
        fields.append(
            _init_field(
                source_field=name,
                target_field=name,
                field_category="dimension",
                sort_order=order,
                description="维度",
            )
        )
        order += 1
    fields.append(
        _init_field(
            source_field="*",
            target_field="注塑机总产量",
            field_category="measure",
            field_type="integer",
            aggregate_func="COUNT",
            sort_order=order,
            description="记录数",
        )
    )
    order += 1
    fields.append(
        _init_field(
            source_field=pick("排次总结果") or "排次总结果",
            target_field="注塑机总不良数",
            field_category="measure",
            field_type="integer",
            aggregate_func="SUM",
            sort_order=order,
            description="排次总结果求和",
        )
    )
    order += 1
    fields.append(
        _init_field(
            source_field=pick("外观总结果") or "外观总结果",
            target_field="自动外观总产量",
            field_category="measure",
            field_type="integer",
            aggregate_func="COUNT",
            sort_order=order,
            description="有外观总结果的记录数",
        )
    )
    order += 1
    fields.append(
        _init_field(
            source_field=pick("外观总结果") or "外观总结果",
            target_field="自动外观总不良数",
            field_category="measure",
            field_type="integer",
            aggregate_func="SUM",
            sort_order=order,
            description="外观总结果求和",
        )
    )
    return {
        "time_field": time_field,
        "granularity": "hour",
        "time_field_name": "hour",
        "lookback_hours": int(model.get("lookback_hours") or 1),
        "backfill_hours": int(model.get("backfill_hours") or 12),
        "columns": columns,
        "fields": fields,
    }


def touch_model_run(model_id: int, *, ok: bool, rows: int, message: str) -> None:
    db = MetaSession()
    try:
        row = db.get(MetaAggModel, int(model_id))
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


def assert_model_runnable(model: dict | None) -> None:
    if not model:
        raise ValueError("聚合模型不存在")
    if model.get("is_draft"):
        raise ValueError("草稿模型不能执行，请先保存聚合配置")
    if not model.get("sql_path"):
        raise ValueError("尚未生成 SQL，请先保存配置")
    if not model.get("is_enabled"):
        raise ValueError("模型未启用")
    if not model.get("project_enabled", True):
        raise ValueError("项目已停用")
    if int(model.get("field_count") or 0) <= 0 and not model.get("fields"):
        raise ValueError("请先配置维度和度量")
