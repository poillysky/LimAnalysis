"""执行 analysis 模型：在 lim_dwh 跑聚合 SELECT，写入 ADS 表。"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from sqlalchemy import text

from app.core import db as stores
from app.core.sql_ident import ident, q
from processor.ads_bi import ads_pg_type, ads_types_match, ensure_ads_for_metabase
from processor.agg_store import assert_model_runnable, get_model, touch_model_run
from processor.executor import (
    _as_copy_cell,
    _copy_rows,
    _dwh_columns,
    _dwh_exists,
    _strip_sql_comments,
)
from processor.sql_rewrite import wrap_source_time_window

logger = logging.getLogger(__name__)


def _read_sql_file(sql_path: str) -> str:
    from processor.sql_generator import resolve_sql_path

    return resolve_sql_path(sql_path, layer="layer2").read_text(encoding="utf-8")


def _analysis_sql(model: dict) -> str:
    if model.get("sql_path"):
        try:
            return _strip_sql_comments(_read_sql_file(model["sql_path"]))
        except FileNotFoundError:
            logger.warning(
                "聚合 SQL 文件缺失，改从字段配置生成: model_id=%s path=%s",
                model.get("id"),
                model.get("sql_path"),
            )
    from processor.sql_generator import (
        generate_analysis_select_sql,
        write_analysis_sql_file,
    )

    fields = model.get("fields") or []
    if not fields:
        raise ValueError("请先配置维度和度量")
    try:
        sql_text, new_path = write_analysis_sql_file(
            model_name=model["name"],
            source_table=model["source_table"],
            target_table=model["target_table"],
            time_field=model["time_field"],
            granularity=model.get("granularity") or "hour",
            time_field_name=model.get("time_field_name") or "时间",
            fields=fields,
            description=f"project={model.get('project_id') or ''}",
        )
        try:
            from processor.agg_store import patch_agg_sql_path

            patch_agg_sql_path(int(model["id"]), new_path)
        except Exception:
            logger.debug("回写聚合 sql_path 失败（可忽略）", exc_info=True)
        return _strip_sql_comments(sql_text)
    except Exception:
        pass
    return _strip_sql_comments(
        generate_analysis_select_sql(
            model_name=model["name"],
            source_table=model["source_table"],
            target_table=model["target_table"],
            time_field=model.get("time_field") or "ServerTime",
            granularity=model.get("granularity") or "hour",
            time_field_name=model.get("time_field_name") or "hour",
            fields=fields,
        )
    )


def _window_start_sql() -> str:
    """整点对齐：从当前小时往回 N 小时，避免截在半小时导致漏桶。"""
    return (
        "date_trunc('hour', NOW()) "
        "- (CAST(:agg_hours AS text) || ' hours')::interval"
    )


def _restrict_source_hours(sql: str, source_table: str, time_field: str) -> str:
    return wrap_source_time_window(
        sql,
        source_table,
        time_field,
        _window_start_sql(),
        quoted_source=q(ident(source_table)),
        quoted_column=q(ident(time_field)),
        context="聚合按小时窗口",
    )


def _restrict_source_from(sql: str, source_table: str, time_field: str) -> str:
    return wrap_source_time_window(
        sql,
        source_table,
        time_field,
        f"{q(ident(time_field))} >= :preview_from",
        quoted_source=q(ident(source_table)),
        quoted_column=q(ident(time_field)),
        context="聚合预览",
    )


def _max_timestamp(table: str, time_field: str):
    sql = f"SELECT MAX({q(ident(time_field))}) FROM {q(ident(table))}"
    with stores.dwh_engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def _fmt_ts(value) -> str:
    if value is None:
        return ""
    return str(value).replace("T", " ")[:19]


def _preview_window(table: str, time_field: str, hours: int) -> tuple[object | None, object | None]:
    anchor = _max_timestamp(table, time_field)
    if anchor is None:
        return None, None
    return anchor - timedelta(hours=max(1, int(hours))), anchor


def _fetch_dwh(sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
    with stores.dwh_engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        columns = [ident(str(k)) for k in result.keys()]
        rows = [[_as_copy_cell(v) for v in rec] for rec in result]
    return columns, rows


def _ads_type_map(model: dict | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in (model or {}).get("fields") or []:
        name = ident(str(field.get("target_field") or "").strip())
        if name:
            out[name] = str(field.get("field_type") or "text")
    return out


def _rebuild_ads(
    columns: list[str],
    rows: list[list],
    target_table: str,
    time_field_name: str = "hour",
    type_map: dict[str, str] | None = None,
) -> int:
    table_i = ident(target_table)
    cols = list(columns) or ["etl_at"]
    types = type_map or {}
    col_defs = ", ".join(
        f"{q(c)} {ads_pg_type(c, time_field_name, types.get(ident(c)))}" for c in cols
    )
    engine = stores.dwh_engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {q(table_i)} CASCADE"))
        conn.execute(text(f"CREATE TABLE {q(table_i)} ({col_defs})"))
        if rows:
            _copy_rows(conn, table_i, columns, rows)
    return len(rows)


def _replace_window(
    columns: list[str],
    rows: list[list],
    target_table: str,
    time_field_name: str,
    hours: int,
    type_map: dict[str, str] | None = None,
) -> int:
    table_i = ident(target_table)
    tf = ident(time_field_name)
    types = type_map or {}
    engine = stores.dwh_engine
    if not _dwh_exists(target_table):
        return _rebuild_ads(columns, rows, target_table, time_field_name, types)

    existing = _dwh_columns(target_table)
    have = {ident(c) for c in existing}
    with engine.begin() as conn:
        for col in columns:
            if col not in have:
                pg_type = ads_pg_type(col, time_field_name, types.get(ident(col)))
                conn.execute(
                    text(f"ALTER TABLE {q(table_i)} ADD COLUMN {q(col)} {pg_type}")
                )
                have.add(col)
        conn.execute(
            text(
                f"""
                DELETE FROM {q(table_i)}
                WHERE {q(tf)} IS NULL
                   OR {q(tf)} >= {_window_start_sql()}
                """
            ),
            {"agg_hours": int(hours)},
        )
        if rows:
            write_cols = [c for c in columns if c in have]
            write_rows = []
            index = {c: i for i, c in enumerate(columns)}
            for rec in rows:
                write_rows.append([rec[index[c]] for c in write_cols])
            _copy_rows(conn, table_i, write_cols, write_rows)
    return len(rows)


def preview_model(model_id: int, *, hours: int | None = None, limit: int = 200) -> dict:
    model = get_model(model_id, include_fields=True)
    if model is None:
        raise ValueError("聚合模型不存在")
    sql = _analysis_sql(model)
    lookback = max(1, int(hours or 1))
    stores.refresh_pg_engines()
    source = model["source_table"]
    time_field = model.get("time_field") or "ServerTime"
    if not _dwh_exists(source):
        raise ValueError(f"清洗表不存在: {source}（请先跑数据清洗）")
    preview_from, anchor = _preview_window(source, time_field, lookback)
    if preview_from is None:
        return {
            "columns": [],
            "rows": [],
            "sql": sql,
            "hours": lookback,
            "from_time": "",
            "to_time": "",
            "source": "dwd",
            "source_table": source,
        }
    run_sql = _restrict_source_from(sql, source, time_field)
    limited = (
        f"SELECT * FROM ({run_sql}) AS _preview LIMIT {int(max(1, min(limit, 500)))}"
    )
    columns, records = _fetch_dwh(limited, {"preview_from": preview_from})
    rows = [dict(zip(columns, rec, strict=True)) for rec in records]
    return {
        "columns": columns,
        "rows": rows,
        "sql": sql,
        "hours": lookback,
        "from_time": _fmt_ts(preview_from),
        "to_time": _fmt_ts(anchor),
        "source": "dwd",
        "source_table": source,
    }


def query_ads(model_id: int, *, hours: int | None = None, limit: int = 500) -> dict:
    model = get_model(model_id, include_fields=False)
    if model is None:
        raise ValueError("聚合模型不存在")
    target = model["target_table"]
    time_col = ident(model.get("time_field_name") or "hour")
    lookback = max(1, int(hours or 1))
    stores.refresh_pg_engines()
    if not _dwh_exists(target):
        return preview_model(model_id, hours=lookback, limit=limit)
    preview_from, anchor = _preview_window(target, time_col, lookback)
    if preview_from is None:
        return {
            "columns": [],
            "rows": [],
            "sql": "",
            "hours": lookback,
            "from_time": "",
            "to_time": "",
            "source": "ads",
            "source_table": target,
        }
    limited = int(max(1, min(limit, 1000)))
    sql = (
        f"SELECT * FROM {q(ident(target))} "
        f"WHERE {q(time_col)} >= :preview_from "
        f"ORDER BY {q(time_col)} DESC "
        f"LIMIT {limited}"
    )
    columns, records = _fetch_dwh(sql, {"preview_from": preview_from})
    rows = [dict(zip(columns, rec, strict=True)) for rec in records]
    return {
        "columns": columns,
        "rows": rows,
        "sql": sql,
        "hours": lookback,
        "from_time": _fmt_ts(preview_from),
        "to_time": _fmt_ts(anchor),
        "source": "ads",
        "source_table": target,
    }


def sql_preview(model_id: int) -> dict:
    model = get_model(model_id, include_fields=True)
    if model is None:
        raise ValueError("聚合模型不存在")
    if model.get("sql_path"):
        try:
            return {"sql": _read_sql_file(model["sql_path"]), "sql_path": model["sql_path"]}
        except FileNotFoundError:
            pass
    sql = _analysis_sql(model)
    return {"sql": sql, "sql_path": model.get("sql_path") or ""}


def execute_model(
    model_id: int, *, full_refresh: bool = False, backfill_hours: int | None = None
) -> dict:
    started = time.time()
    model = get_model(model_id, include_fields=True)
    assert_model_runnable(model)
    assert model is not None

    sql = _analysis_sql(model)
    source = model["source_table"]
    target = model["target_table"]
    time_field = model.get("time_field") or "ServerTime"
    time_out = model.get("time_field_name") or "hour"
    raw_hours = (
        backfill_hours if backfill_hours is not None else (model.get("backfill_hours") or 12)
    )
    hours = int(raw_hours)

    stores.refresh_pg_engines()
    if not _dwh_exists(source):
        raise ValueError(f"清洗表不存在: {source}（请先跑数据清洗）")

    type_map = _ads_type_map(model)
    type_map.setdefault(ident(time_out), "datetime")
    type_map.setdefault("etl_at", "datetime")
    mode = "full" if full_refresh or not _dwh_exists(target) else "incremental"
    if mode == "incremental":
        fields = model.get("fields") or []
        probe = [ident(f["target_field"]) for f in fields if f.get("target_field")]
        probe.extend([ident(time_out), "etl_at"])
        if not ads_types_match(target, probe, time_out, type_map):
            logger.warning("ads %s column types mismatch model; forcing full refresh", target)
            mode = "full"
    run_sql = sql
    params: dict = {}
    if mode == "incremental":
        run_sql = _restrict_source_hours(sql, source, time_field)
        params = {"agg_hours": hours}

    logger.info(
        "agg execute model#%s %s → %s mode=%s hours=%s",
        model_id,
        source,
        target,
        mode,
        hours,
    )
    try:
        columns, records = _fetch_dwh(run_sql, params)
        if mode == "incremental":
            rows = _replace_window(columns, records, target, time_out, hours, type_map)
            msg = f"增量回算 {hours} 小时写入 {target}（{rows:,} 行）"
        else:
            rows = _rebuild_ads(columns, records, target, time_out, type_map)
            msg = f"全量重建 {target}（{rows:,} 行）"
        try:
            ensure_ads_for_metabase(target, time_out)
        except Exception:
            logger.exception("ADS Metabase 视图未更新: %s", target)
        touch_model_run(model_id, ok=True, rows=rows, message=msg)
        return {
            "ok": True,
            "model_id": model_id,
            "project_id": model["project_id"],
            "source_table": source,
            "target_table": target,
            "mode": mode,
            "backfill_hours": hours,
            "source_rows": len(records),
            "rows": rows,
            "duration": round(time.time() - started, 3),
            "message": msg,
        }
    except Exception as exc:
        err = str(exc)[:500]
        touch_model_run(model_id, ok=False, rows=0, message=err)
        raise


def execute_project(
    project_id: str, *, full_refresh: bool = False, backfill_hours: int | None = None
) -> dict:
    from processor.agg_store import get_model_by_project

    model = get_model_by_project(project_id, include_fields=True)
    if model is None:
        raise ValueError("聚合模型不存在")
    return execute_model(
        int(model["id"]), full_refresh=full_refresh, backfill_hours=backfill_hours
    )


def execute_all_enabled(
    *, full_refresh: bool = False, backfill_hours: int | None = None
) -> dict:
    from processor.agg_store import list_models

    results = []
    errors = []
    for model in list_models():
        if not model.get("can_run"):
            continue
        try:
            results.append(
                execute_model(
                    int(model["id"]),
                    full_refresh=full_refresh,
                    backfill_hours=backfill_hours,
                )
            )
        except Exception as exc:
            logger.exception("agg model#%s failed", model.get("id"))
            errors.append(
                {
                    "model_id": model.get("id"),
                    "project_id": model.get("project_id"),
                    "error": str(exc)[:300],
                }
            )
    if not results and not errors:
        raise ValueError("没有可执行的已启用聚合模型（需：保存配置、生成 SQL、启用）")
    return {
        "ok": len(errors) == 0,
        "projects": results,
        "errors": errors,
        "total_rows": sum(int(r.get("rows") or 0) for r in results),
    }
