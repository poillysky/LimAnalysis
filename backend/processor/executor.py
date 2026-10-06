"""
执行 link 模型：在 lim_raw 跑 SELECT，将结果写入 lim_dwh。

默认增量：只读原表 ingested_at 之后更新的行，按唯一键 UPSERT。
目标表不存在、无唯一键、或显式全量时，才 DROP 重建。
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.core import db as stores
from app.core.sql_ident import ident, q
from processor.field_types import normalize_field_type, pg_type_for_field_type
from processor.models_store import (
    assert_model_runnable,
    get_model,
    get_model_by_project,
    list_fields,
    touch_model_run,
)
from processor.sql_rewrite import wrap_source_time_window

logger = logging.getLogger(__name__)


def _read_sql_file(sql_path: str) -> str:
    path = Path(sql_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / sql_path
    if not path.exists():
        # models_store 写的是绝对路径；兼容相对
        alt = Path(__file__).resolve().parent / "sql_models" / "layer1" / path.name
        if alt.exists():
            path = alt
        else:
            raise FileNotFoundError(f"SQL 文件不存在: {sql_path}")
    return path.read_text(encoding="utf-8")


def _strip_sql_comments(sql: str) -> str:
    lines = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def preview_model(model_id: int, *, limit: int = 50) -> dict:
    model = get_model(model_id, include_fields=True)
    if model is None:
        raise ValueError("模型不存在")
    if not model.get("sql_path") and not model.get("fields"):
        raise ValueError("请先配置并保存字段映射")
    if model.get("sql_path"):
        sql = _strip_sql_comments(_read_sql_file(model["sql_path"]))
    else:
        from processor.sql_generator import generate_link_select_sql

        sql = _strip_sql_comments(
            generate_link_select_sql(
                model_name=model["name"],
                source_table=model["source_table"],
                target_table=model["target_table"],
                fields=model.get("fields") or [],
                unique_key=model.get("unique_key") or "",
            )
        )
    stores.refresh_pg_engines()
    limited = f"SELECT * FROM ({sql}) AS _preview LIMIT {int(max(1, min(limit, 200)))}"
    columns, records = _fetch_rows(limited)
    rows = [dict(zip(columns, rec, strict=True)) for rec in records]
    return {"columns": columns, "rows": rows, "sql": sql}


def sql_preview(model_id: int) -> dict:
    model = get_model(model_id, include_fields=True)
    if model is None:
        raise ValueError("模型不存在")
    if model.get("sql_path"):
        try:
            sql = _read_sql_file(model["sql_path"])
            return {"sql": sql, "sql_path": model["sql_path"]}
        except FileNotFoundError:
            pass
    from processor.sql_generator import generate_link_select_sql

    fields = model.get("fields") or list_fields(model_id)
    if not fields:
        raise ValueError("请先配置字段映射")
    sql = generate_link_select_sql(
        model_name=model["name"],
        source_table=model["source_table"],
        target_table=model["target_table"],
        fields=fields,
        unique_key=model.get("unique_key") or "",
    )
    return {"sql": sql, "sql_path": model.get("sql_path") or ""}


def _dwh_exists(table: str) -> bool:
    table_i = ident(table)
    with stores.dwh_engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :t
                    LIMIT 1
                    """
                ),
                {"t": table_i},
            ).scalar()
        )


def _dwh_columns(table: str) -> list[str]:
    table_i = ident(table)
    with stores.dwh_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
                ORDER BY ordinal_position
                """
            ),
            {"t": table_i},
        ).fetchall()
    return [str(r[0]) for r in rows]


def _raw_has_column(table: str, column: str) -> bool:
    with stores.raw_engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :t
                      AND column_name = :c
                    LIMIT 1
                    """
                ),
                {"t": ident(table), "c": ident(column)},
            ).scalar()
        )


def _dwh_watermark(table: str) -> str | None:
    """用清洗表 etl_at 最大值作水位；重叠 2 分钟，避免漏更。"""
    if not _dwh_exists(table):
        return None
    cols = {ident(c) for c in _dwh_columns(table)}
    if "etl_at" not in cols:
        return None
    with stores.dwh_engine.connect() as conn:
        value = conn.execute(
            text(
                f"""
                SELECT MAX({q("etl_at")}::timestamptz) - INTERVAL '2 minutes'
                FROM {q(ident(table))}
                """
            )
        ).scalar()
    if value is None:
        return None
    return str(value)


def _restrict_source_sql(sql: str, source_table: str, inc_col: str) -> str:
    return wrap_source_time_window(
        sql,
        source_table,
        inc_col,
        f"{q(ident(inc_col))} > CAST(:etl_wm AS timestamptz)",
        quoted_source=q(ident(source_table)),
        quoted_column=q(ident(inc_col)),
        context="ETL 增量清洗",
    )


def _as_copy_cell(value):
    """COPY 单元：NULL 保持 None；datetime/数值保留原生类型；其余转 str。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (datetime, date, dt_time, Decimal, int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _field_type_map(model: dict | None) -> dict[str, str]:
    """target_field → field_type；etl_at 固定时间。"""
    out: dict[str, str] = {"etl_at": "datetime"}
    for field in (model or {}).get("fields") or []:
        name = ident(str(field.get("target_field") or "").strip())
        if not name:
            continue
        out[name] = normalize_field_type(field.get("field_type"))
    return out


def _col_pg_type(column: str, type_map: dict[str, str], *, pk: str = "") -> str:
    col = ident(column)
    if col == "etl_at":
        return "TIMESTAMPTZ"
    if col in type_map:
        return pg_type_for_field_type(type_map[col])
    if pk and col == ident(pk):
        return "TEXT"
    return "TEXT"


def _dwh_udt_map(table: str) -> dict[str, str]:
    table_i = ident(table)
    with stores.dwh_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
                """
            ),
            {"t": table_i},
        ).fetchall()
    return {str(r[0]): str(r[1]).lower() for r in rows}


def _dwh_types_match(table: str, columns: list[str], type_map: dict[str, str], pk: str) -> bool:
    """存量 DWD 列类型是否已与模型一致；不一致则应全量重建。"""
    have = _dwh_udt_map(table)
    if not have:
        return False
    expect_udt = {
        "TEXT": {"text", "varchar", "bpchar"},
        "BIGINT": {"int8", "int4", "int2"},
        "NUMERIC": {"numeric", "float4", "float8", "int8", "int4", "int2"},
        "TIMESTAMPTZ": {"timestamptz", "timestamp"},
        "SMALLINT": {"int2", "int4", "int8"},
    }
    for col in columns:
        want = _col_pg_type(col, type_map, pk=pk)
        udt = have.get(ident(col))
        if udt is None:
            return False
        if udt not in expect_udt.get(want, {want.lower()}):
            return False
    return True


def _fetch_rows(sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
    """在 lim_raw 执行 SELECT。NULL 保持 Python None，不经过 pandas。"""
    with stores.raw_engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = [ident(str(k)) for k in result.keys()]
        rows = [[_as_copy_cell(v) for v in rec] for rec in result]
    return columns, rows


def _copy_rows(conn, table_i: str, columns: list[str], rows: list[list]) -> None:
    col_sql = ", ".join(q(c) for c in columns)
    raw = conn.connection.driver_connection
    with raw.cursor() as cur, cur.copy(f"COPY {q(table_i)} ({col_sql}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def _rebuild_dwh(
    columns: list[str],
    rows: list[list],
    target_table: str,
    unique_key: str,
    type_map: dict[str, str] | None = None,
) -> int:
    table_i = ident(target_table)
    pk = ident(unique_key) if unique_key else ""
    types = dict(type_map or {})
    engine = stores.dwh_engine
    cols = list(columns) or ([pk] if pk else ["etl_at"])
    if pk and pk not in cols:
        cols = [pk, *cols]
    if "etl_at" not in cols:
        cols.append("etl_at")

    def _defs(names: list[str], *, with_pk: bool) -> str:
        parts = []
        for c in names:
            pg = _col_pg_type(c, types, pk=pk)
            suffix = " PRIMARY KEY" if with_pk and pk and c == pk else ""
            parts.append(f"{q(c)} {pg}{suffix}")
        return ", ".join(parts)

    if not rows:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {q(table_i)} CASCADE"))
            conn.execute(text(f"CREATE TABLE {q(table_i)} ({_defs(cols, with_pk=True)})"))
        return 0

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {q(table_i)} CASCADE"))
        if pk and pk in columns:
            conn.execute(text(f"CREATE TABLE {q(table_i)} ({_defs(columns, with_pk=False)})"))
        else:
            conn.execute(text(f"CREATE TABLE {q(table_i)} ({_defs(columns, with_pk=True)})"))
        _copy_rows(conn, table_i, columns, rows)
        if pk and pk in columns:
            conn.execute(text(f"ALTER TABLE {q(table_i)} ADD PRIMARY KEY ({q(pk)})"))
    return len(rows)


def _upsert_dwh(
    columns: list[str],
    rows: list[list],
    target_table: str,
    unique_key: str,
    type_map: dict[str, str] | None = None,
) -> int:
    """按唯一键 UPSERT，不删清洗表。列类型按模型 field_type。"""
    if not rows:
        return 0
    table_i = ident(target_table)
    pk = ident(unique_key)
    types = dict(type_map or {})
    if pk not in columns:
        raise ValueError(f"增量写入需要唯一键列 {pk} 出现在清洗结果中")
    engine = stores.dwh_engine
    existing = _dwh_columns(target_table)
    have = {ident(c) for c in existing}
    with engine.begin() as conn:
        if not existing:
            defs = ", ".join(
                f"{q(c)} {_col_pg_type(c, types, pk=pk)}" for c in columns
            )
            conn.execute(text(f"CREATE TABLE {q(table_i)} ({defs})"))
            have = set(columns)
        for col in columns:
            if col not in have:
                pg = _col_pg_type(col, types, pk=pk)
                conn.execute(text(f"ALTER TABLE {q(table_i)} ADD COLUMN {q(col)} {pg}"))
                have.add(col)
        pk_ok = conn.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class r ON r.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = r.relnamespace
                WHERE n.nspname = 'public'
                  AND r.relname = :t
                  AND c.contype IN ('p', 'u')
                LIMIT 1
                """
            ),
            {"t": table_i},
        ).scalar()
        if not pk_ok:
            conn.execute(text(f"ALTER TABLE {q(table_i)} ADD PRIMARY KEY ({q(pk)})"))
        temp = ident(f"_stg_{table_i}")[:60]
        col_sql = ", ".join(q(c) for c in columns)
        defs = ", ".join(f"{q(c)} {_col_pg_type(c, types, pk=pk)}" for c in columns)
        updates = ", ".join(
            f"{q(c)} = EXCLUDED.{q(c)}" for c in columns if c != pk
        )
        conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {q(temp)}")
            cur.execute(f"CREATE TEMP TABLE {q(temp)} ({defs}) ON COMMIT DROP")
            with cur.copy(f"COPY {q(temp)} ({col_sql}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            order_extra = f", {q('etl_at')} DESC NULLS LAST" if "etl_at" in columns else ""
            cur.execute(
                f"""
                INSERT INTO {q(table_i)} ({col_sql})
                SELECT DISTINCT ON ({q(pk)}) {col_sql}
                FROM {q(temp)}
                ORDER BY {q(pk)}{order_extra}
                ON CONFLICT ({q(pk)}) {conflict}
                """
            )
    return len(rows)


def execute_model(model_id: int, *, full_refresh: bool = False) -> dict:
    started = time.time()
    model = get_model(model_id, include_fields=True)
    assert_model_runnable(model)
    assert model is not None

    sql_path = model["sql_path"]
    sql = _strip_sql_comments(_read_sql_file(sql_path))
    source = model["source_table"]
    target = model["target_table"]
    unique_key = model.get("unique_key") or ""
    inc_col = ident(str(model.get("incremental_field") or "ingested_at"))

    stores.refresh_pg_engines()
    if not _raw_has_column(source, inc_col):
        inc_col = "ingested_at"
    type_map = _field_type_map(model)
    can_incremental = (
        not full_refresh
        and bool(unique_key)
        and _dwh_exists(target)
        and _raw_has_column(source, inc_col)
    )
    # 类型与模型不一致时必须全量重建，禁止在 TEXT 表上继续打补丁
    if can_incremental:
        # 先读一列名：用已有 SQL 列序判断（执行前未知列时用模型 target 字段）
        fields = model.get("fields") or []
        probe_cols = [ident(f["target_field"]) for f in fields if f.get("target_field")]
        probe_cols.append("etl_at")
        if not _dwh_types_match(target, probe_cols, type_map, unique_key):
            logger.warning("dwd %s column types mismatch model; forcing full refresh", target)
            can_incremental = False
    mode = "incremental" if can_incremental else "full"
    watermark = _dwh_watermark(target) if can_incremental else None
    run_sql = sql
    if can_incremental and watermark:
        run_sql = _restrict_source_sql(sql, source, inc_col)

    logger.info(
        "etl execute model#%s %s → %s mode=%s wm=%s",
        model_id,
        source,
        target,
        mode,
        watermark or "-",
    )
    try:
        params = {"etl_wm": watermark} if (can_incremental and watermark) else {}
        columns, records = _fetch_rows(run_sql, params)
        if mode == "incremental":
            rows = _upsert_dwh(columns, records, target, unique_key, type_map)
            msg = f"增量写入 {target}（{rows:,} 行）"
        else:
            rows = _rebuild_dwh(columns, records, target, unique_key, type_map)
            msg = f"全量重建 {target}（{rows:,} 行）"
        _touch_project_summary(model["project_id"], True, rows, msg)
        touch_model_run(model_id, ok=True, rows=rows, message=msg)
        return {
            "ok": True,
            "model_id": model_id,
            "project_id": model["project_id"],
            "source_table": source,
            "target_table": target,
            "unique_key": unique_key,
            "mode": mode,
            "watermark": watermark or "",
            "source_rows": len(records),
            "rows": rows,
            "duration": round(time.time() - started, 3),
            "message": msg,
        }
    except Exception as exc:
        err = str(exc)[:500]
        touch_model_run(model_id, ok=False, rows=0, message=err)
        _touch_project_summary(model["project_id"], False, 0, err)
        raise


def execute_project(project_id: str, *, full_refresh: bool = False) -> dict:
    model = get_model_by_project(project_id, include_fields=True)
    if model is None:
        raise ValueError("模型不存在，请先打开数据清洗页生成模型")
    return execute_model(int(model["id"]), full_refresh=full_refresh)


def execute_all_enabled(*, full_refresh: bool = False) -> dict:
    from processor.models_store import list_models

    results = []
    errors = []
    for model in list_models():
        if not model.get("can_run"):
            continue
        try:
            results.append(execute_model(int(model["id"]), full_refresh=full_refresh))
        except Exception as exc:
            logger.exception("etl model#%s failed", model.get("id"))
            errors.append(
                {
                    "model_id": model.get("id"),
                    "project_id": model.get("project_id"),
                    "error": str(exc)[:300],
                }
            )
    if not results and not errors:
        raise ValueError("没有可执行的已启用模型（需：保存字段映射、生成 SQL、启用）")
    return {
        "ok": len(errors) == 0,
        "projects": results,
        "errors": errors,
        "total_rows": sum(int(r.get("rows") or 0) for r in results),
    }


def _touch_project_summary(project_id: str, ok: bool, rows: int, message: str) -> None:
    from datetime import datetime

    from app.core.db import MetaSession
    from app.core.meta_models import MetaProject

    db = MetaSession()
    try:
        row = db.get(MetaProject, project_id)
        if row is None:
            return
        config = dict(row.config or {})
        config["last_etl_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        config["last_etl_status"] = "success" if ok else "failed"
        config["last_etl_rows"] = int(rows)
        config["last_etl_message"] = str(message or "")[:200]
        row.config = config
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("更新项目 ETL 状态失败")
    finally:
        db.close()
