"""
根据字段映射生成 PostgreSQL SELECT（对齐 etl-app SqlGenerator link 层）。

双库隔离：只生成针对 lim_raw 源表的 SELECT，不写跨库 JOIN。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.sql_ident import ident, q
from processor.field_types import cast_direct_expr, coerce_sql_to_field_type

SQL_MODELS_DIR = Path(__file__).resolve().parent / "sql_models"


def process_formula(formula: str) -> str:
    """将 [字段] / `字段` / 【字段】 规范为 PostgreSQL "字段"。"""
    text = str(formula or "").strip()
    text = text.replace("【", "[").replace("】", "]")

    def _bracket(match: re.Match) -> str:
        return q(ident(match.group(1)))

    text = re.sub(r"\[([^\]]+)\]", _bracket, text)
    text = re.sub(r"`([^`]+)`", _bracket, text)
    return text


def _join_select_lines(parts: list[str]) -> str:
    if not parts:
        return "    1 AS _empty"
    lines = []
    for i, part in enumerate(parts):
        suffix = "," if i < len(parts) - 1 else ""
        lines.append(f"{part}{suffix}")
    return "\n".join(lines)


def generate_link_select_sql(
    *,
    model_name: str,
    source_table: str,
    target_table: str,
    fields: list[dict[str, Any]],
    unique_key: str = "",
    description: str = "",
) -> str:
    """生成可在 lim_raw 上执行的 SELECT SQL 文本。"""
    source = ident(source_table)
    target = ident(target_table)
    header = [
        f"-- link 模型: {model_name}",
        f"-- 描述: {description or '无'}",
        f"-- 源表(lim_raw): {source}",
        f"-- 目标表(lim_dwh): {target}",
        f"-- 唯一键: {unique_key or '无'}",
        "-- 执行: Worker 在 raw 跑本 SELECT（增量时按 ingested_at 过滤），再写入 dwh",
        "--",
        "",
    ]

    direct_exprs: list[str] = []
    direct_targets: list[str] = []
    level1: list[str] = []
    level1_targets: list[str] = []
    level2: list[str] = []
    constants: list[str] = []

    for field in fields:
        mapping_type = str(field.get("mapping_type") or "direct").strip().lower()
        target_field = ident(str(field.get("target_field") or "").strip())
        if not target_field:
            continue
        derive_level = int(field.get("derive_level") or 1)

        if mapping_type == "direct":
            source_field = ident(
                str(field.get("source_field") or field.get("target_field") or "").strip()
            )
            expr = cast_direct_expr(
                source_field,
                target_field,
                str(field.get("field_type") or "text"),
            )
            direct_exprs.append(expr)
            direct_targets.append(target_field)
        elif mapping_type == "derived":
            formula = process_formula(str(field.get("formula") or ""))
            if not formula:
                continue
            typed = coerce_sql_to_field_type(
                formula, str(field.get("field_type") or "text")
            )
            expr = f"    {typed} AS {q(target_field)}"
            if derive_level >= 2:
                level2.append(expr)
            else:
                level1.append(expr)
                level1_targets.append(target_field)
        elif mapping_type == "constant":
            value = str(field.get("constant_value") if field.get("constant_value") is not None else "")
            escaped = value.replace("'", "''")
            typed = coerce_sql_to_field_type(
                f"'{escaped}'", str(field.get("field_type") or "text")
            )
            constants.append(f"    {typed} AS {q(target_field)}")

    use_cte = bool(level2)
    if use_cte:
        cte_parts = list(direct_exprs) + list(level1)
        main_parts = [f"    {q(t)}" for t in direct_targets + level1_targets]
        main_parts.extend(level2)
        main_parts.extend(constants)
        main_parts.append("    NOW() AS etl_at")
        sql = (
            f"{chr(10).join(header)}"
            f"WITH level1 AS (\n"
            f"    SELECT\n"
            f"{_join_select_lines(cte_parts)}\n"
            f"    FROM {q(source)}\n"
            f")\n"
            f"SELECT\n"
            f"{_join_select_lines(main_parts)}\n"
            f"FROM level1\n"
        )
    else:
        parts = list(direct_exprs) + list(level1) + list(constants)
        parts.append("    NOW() AS etl_at")
        sql = (
            f"{chr(10).join(header)}"
            f"SELECT\n"
            f"{_join_select_lines(parts)}\n"
            f"FROM {q(source)}\n"
        )
    return sql


def write_link_sql_file(
    *,
    model_name: str,
    source_table: str,
    target_table: str,
    fields: list[dict[str, Any]],
    unique_key: str = "",
    description: str = "",
) -> tuple[str, str]:
    """生成 SQL 并写入文件，返回 (sql_text, relative_or_absolute_path)。"""
    sql = generate_link_select_sql(
        model_name=model_name,
        source_table=source_table,
        target_table=target_table,
        fields=fields,
        unique_key=unique_key,
        description=description,
    )
    layer = SQL_MODELS_DIR / "layer1"
    layer.mkdir(parents=True, exist_ok=True)
    path = layer / f"{ident(target_table)}.sql"
    path.write_text(sql, encoding="utf-8")
    return sql, str(path)


_GRAIN_TRUNC = {"hour": "hour", "day": "day", "week": "week", "month": "month"}


def time_bucket_expr(time_field: str, granularity: str) -> str:
    """DWD 时间列应为 timestamptz，直接 date_trunc。"""
    grain = _GRAIN_TRUNC.get(str(granularity or "hour").strip().lower(), "hour")
    col = q(ident(time_field))
    return f"date_trunc('{grain}', {col})"


def generate_analysis_select_sql(
    *,
    model_name: str,
    source_table: str,
    target_table: str,
    time_field: str,
    granularity: str,
    time_field_name: str,
    fields: list[dict[str, Any]],
    description: str = "",
) -> str:
    """生成可在 lim_dwh 上执行的聚合 SELECT（对齐 etl-app analysis 层，PG 方言）。

    假定清洗表时间/布尔/数值列类型正确（timestamptz / smallint / numeric）。
    """
    source = ident(source_table)
    target = ident(target_table)
    time_out = ident(time_field_name or granularity or "hour")
    grain = str(granularity or "hour").strip().lower()
    if grain not in _GRAIN_TRUNC:
        grain = "hour"

    dimensions: list[dict[str, Any]] = []
    measures: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    for field in fields:
        category = str(field.get("field_category") or "").strip().lower()
        level = int(field.get("derive_level") or 1)
        if category == "dimension":
            dimensions.append(field)
        elif category == "measure":
            measures.append(field)
        elif category == "derived" or (category == "" and level >= 2):
            derived.append(field)

    bucket = time_bucket_expr(time_field, grain)
    select_parts = [f"    {bucket} AS {q(time_out)}"]
    group_by_parts = [bucket]
    for dim in dimensions:
        src = ident(str(dim.get("source_field") or "").strip())
        dst = ident(str(dim.get("target_field") or dim.get("source_field") or "").strip())
        if not src or not dst:
            continue
        select_parts.append(f"    {q(src)} AS {q(dst)}")
        group_by_parts.append(q(src))

    for measure in measures:
        dst = ident(str(measure.get("target_field") or "").strip())
        if not dst:
            continue
        func = str(measure.get("aggregate_func") or "COUNT").strip().upper()
        src_raw = str(measure.get("source_field") or "").strip()
        if func == "COUNT" and (not src_raw or src_raw == "*"):
            select_parts.append(f"    COUNT(*) AS {q(dst)}")
            continue
        src = q(ident(src_raw))
        if func == "COUNT":
            select_parts.append(f"    COUNT({src}) AS {q(dst)}")
        elif func == "COUNT_DISTINCT":
            select_parts.append(f"    COUNT(DISTINCT {src}) AS {q(dst)}")
        elif func in {"SUM", "AVG", "MAX", "MIN"}:
            select_parts.append(f"    {func}({src}) AS {q(dst)}")
        else:
            select_parts.append(f"    COUNT(*) AS {q(dst)}")

    header = [
        f"-- analysis 模型: {model_name}",
        f"-- 描述: {description or '无'}",
        f"-- 源表(lim_dwh): {source}",
        f"-- 目标表(lim_dwh): {target}",
        f"-- 时间字段: {ident(time_field)} → {time_out} ({grain})",
        "-- 执行: 独立聚合 Worker 在 dwh 跑本 SELECT，写入 ADS",
        "--",
        "",
    ]
    group_sql = ", ".join(group_by_parts) if group_by_parts else "1"
    time_src = q(ident(time_field))
    outer_parts = ["    aggregated.*"]
    for item in derived:
        dst = ident(str(item.get("target_field") or "").strip())
        formula = process_formula(str(item.get("formula") or ""))
        if dst and formula:
            typed = coerce_sql_to_field_type(
                formula, str(item.get("field_type") or "text")
            )
            outer_parts.append(f"    {typed} AS {q(dst)}")
    outer_parts.append("    NOW() AS etl_at")

    sql = (
        f"{chr(10).join(header)}"
        f"WITH aggregated AS (\n"
        f"    SELECT\n"
        f"{_join_select_lines(select_parts)}\n"
        f"    FROM {q(source)}\n"
        f"    WHERE {time_src} IS NOT NULL\n"
        f"    GROUP BY {group_sql}\n"
        f")\n"
        f"SELECT\n"
        f"{_join_select_lines(outer_parts)}\n"
        f"FROM aggregated\n"
        f"ORDER BY {q(time_out)} DESC\n"
    )
    return sql


def write_analysis_sql_file(
    *,
    model_name: str,
    source_table: str,
    target_table: str,
    time_field: str,
    granularity: str,
    time_field_name: str,
    fields: list[dict[str, Any]],
    description: str = "",
) -> tuple[str, str]:
    sql = generate_analysis_select_sql(
        model_name=model_name,
        source_table=source_table,
        target_table=target_table,
        time_field=time_field,
        granularity=granularity,
        time_field_name=time_field_name,
        fields=fields,
        description=description,
    )
    layer = SQL_MODELS_DIR / "layer2"
    layer.mkdir(parents=True, exist_ok=True)
    path = layer / f"{ident(target_table)}.sql"
    path.write_text(sql, encoding="utf-8")
    return sql, str(path)
