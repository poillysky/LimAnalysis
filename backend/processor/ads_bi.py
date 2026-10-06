"""ADS 给 Metabase：列类型/索引正确，只维护一个近 3 小时宽表视图。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core import db as stores
from app.core.sql_ident import ident, q


def ads_prefix(target_table: str) -> str:
    name = ident(target_table)
    return name[:-4] if name.endswith("_ads") else name


def ads_pg_type(
    column: str,
    time_field_name: str = "hour",
    field_type: str | None = None,
) -> str:
    """优先用聚合模型 field_type；否则按列名约定（时间桶 / 产量不良）。"""
    from processor.field_types import normalize_field_type, pg_type_for_field_type

    col = ident(column)
    if field_type:
        return pg_type_for_field_type(normalize_field_type(field_type))
    if col == ident(time_field_name) or col == "etl_at":
        return "TIMESTAMPTZ"
    if col.endswith("产量") or col.endswith("不良数") or col.endswith("不良率") or col.endswith("良率"):
        return "NUMERIC"
    return "TEXT"


def _existing_columns(table: str) -> list[str]:
    insp = inspect(stores.dwh_engine)
    if not insp.has_table(ident(table)):
        return []
    return [str(c["name"]) for c in insp.get_columns(ident(table))]


def _udt_name(table: str, column: str) -> str:
    with stores.dwh_engine.connect() as conn:
        val = conn.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :t
                  AND column_name = :c
                """
            ),
            {"t": ident(table), "c": ident(column)},
        ).scalar()
    return str(val or "").lower()


def _drop_bi_views(prefix: str) -> None:
    """清掉旧补丁视图与当前 3h 视图（再重建）。"""
    names = (
        f"v_{prefix}_ads_3h",
        f"v_{prefix}_defect_long_3h",
        f"v_{prefix}_defect_long",
        f"v_{prefix}_ads_typed",
    )
    with stores.dwh_engine.begin() as conn:
        for name in names:
            conn.execute(text(f"DROP VIEW IF EXISTS {q(ident(name))} CASCADE"))


def ads_types_match(
    target_table: str,
    columns: list[str],
    time_field_name: str,
    type_map: dict[str, str] | None = None,
) -> bool:
    """存量 ADS 列类型是否已与模型一致；不一致应全量重建，不要 ALTER 打补丁。"""
    table = ident(target_table)
    if not inspect(stores.dwh_engine).has_table(table):
        return False
    types = type_map or {}
    expect = {
        "TEXT": {"text", "varchar", "bpchar"},
        "BIGINT": {"int8", "int4", "int2"},
        "NUMERIC": {"numeric", "float4", "float8", "int8", "int4", "int2"},
        "TIMESTAMPTZ": {"timestamptz", "timestamp"},
        "SMALLINT": {"int2", "int4", "int8"},
    }
    for col in columns:
        want = ads_pg_type(col, time_field_name, types.get(ident(col)))
        have = _udt_name(table, col)
        if not have:
            return False
        if have not in expect.get(want, {want.lower()}):
            return False
    return True


def ensure_ads_time_index(target_table: str, time_field_name: str = "hour") -> None:
    table = ident(target_table)
    if not inspect(stores.dwh_engine).has_table(table):
        return
    idx = f"idx_{table}_{ident(time_field_name)}"
    with stores.dwh_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {ident(idx)} "
                f"ON {q(table)} ({q(ident(time_field_name))})"
            )
        )


def refresh_bi_views(target_table: str, time_field_name: str = "hour") -> dict:
    """只建数据最新 3 小时宽表切片（给 Metabase）。"""
    table = ident(target_table)
    prefix = ads_prefix(table)
    tf = ident(time_field_name)
    cols = _existing_columns(table)
    if not cols:
        return {"ok": False, "reason": "ads_missing"}

    ads_3h = ident(f"v_{prefix}_ads_3h")
    window = f"(SELECT max({q(tf)}) - interval '2 hours' FROM {q(table)})"
    sql = (
        f"CREATE OR REPLACE VIEW {q(ads_3h)} AS\n"
        f"SELECT * FROM {q(table)}\n"
        f"WHERE {q(tf)} IS NOT NULL AND {q(tf)} >= {window}"
    )
    with stores.dwh_engine.begin() as conn:
        conn.execute(text(sql))

    return {
        "ok": True,
        "table": table,
        "ads_3h": ads_3h,
    }


def ensure_ads_for_metabase(target_table: str, time_field_name: str = "hour") -> dict:
    stores.refresh_pg_engines()
    _drop_bi_views(ads_prefix(target_table))
    ensure_ads_time_index(target_table, time_field_name)
    views = refresh_bi_views(target_table, time_field_name)
    return views


def ensure_all_ads_for_metabase() -> list[dict]:
    from processor.agg_store import list_models

    stores.refresh_pg_engines()
    out: list[dict] = []
    for model in list_models():
        target = str(model.get("target_table") or "").strip()
        if not target:
            continue
        time_out = str(model.get("time_field_name") or "hour")
        try:
            out.append(ensure_ads_for_metabase(target, time_out))
        except Exception as exc:
            out.append({"ok": False, "table": target, "error": str(exc)[:300]})
    return out
