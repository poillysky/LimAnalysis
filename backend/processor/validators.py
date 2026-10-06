"""ETL 字段映射校验（对齐 etl-app validators，方言改为 PostgreSQL）。"""

from __future__ import annotations

import re
from typing import Any

_FIELD_NAME = re.compile(r"^[\w\u4e00-\u9fff]+$", re.UNICODE)

# is_safe_sql_expression 原在本文件，现下沉到 app.core.sql_ident：
# 它是纯 SQL 关键字黑名单校验，app.core.ai_client 也要用。住在 processor 里
# 会逼着 app 反向依赖 processor。保留 re-export 兼容既有调用方，实现只有一份。
from app.core.sql_ident import is_safe_sql_expression

__all__ = [
    "is_safe_sql_expression",
    "is_valid_field_name",
    "validate_agg_field",
    "validate_agg_fields",
    "validate_agg_model",
    "validate_field_mapping",
    "validate_fields",
]


def is_valid_field_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text or len(text) > 100:
        return False
    return bool(_FIELD_NAME.fullmatch(text.replace(" ", "_")))


def validate_field_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    mapping_type = str(mapping.get("mapping_type") or "direct").strip().lower()
    target = str(mapping.get("target_field") or "").strip()
    if not target:
        errors.append("缺少目标字段 target_field")
    # 允许经 ident 规范化前的中文名；仅拦空/过长
    elif not is_valid_field_name(target.replace("-", "_")) and len(target) > 100:
        errors.append(f"目标字段名过长: {target}")

    if mapping_type not in {"direct", "derived", "constant"}:
        errors.append(f"不支持的 mapping_type: {mapping_type}")

    if mapping_type == "direct":
        source = str(mapping.get("source_field") or "").strip()
        if not source:
            errors.append(f"直接映射必须提供 source_field（目标 {target or '?'}）")
    elif mapping_type == "derived":
        formula = str(mapping.get("formula") or "").strip()
        if not formula:
            errors.append(f"派生字段必须提供 formula（目标 {target or '?'}）")
        elif not is_safe_sql_expression(formula):
            errors.append(f"公式不安全或非法: {target or '?'}")
        level = int(mapping.get("derive_level") or 1)
        if level not in (1, 2):
            errors.append(f"derive_level 仅支持 1 或 2（目标 {target or '?'}）")
    elif mapping_type == "constant":
        if str(mapping.get("constant_value") or "") == "":
            errors.append(f"固定值字段必须提供 constant_value（目标 {target or '?'}）")

    return {"valid": len(errors) == 0, "errors": errors}


_AGG_FUNCS = {"COUNT", "SUM", "AVG", "MAX", "MIN", "COUNT_DISTINCT"}
_AGG_CATEGORIES = {"dimension", "measure", "derived"}
_AGG_GRAINS = {"hour", "day", "week", "month"}


def validate_agg_model(model: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    time_field = str(model.get("time_field") or "").strip()
    if not time_field:
        errors.append("请选择时间字段")
    grain = str(model.get("granularity") or "hour").strip().lower()
    if grain not in _AGG_GRAINS:
        errors.append("聚合细度仅支持 hour/day/week/month")
    lookback = int(model.get("lookback_hours") or 1)
    backfill = int(model.get("backfill_hours") or 12)
    if lookback < 1 or lookback > 24 * 14:
        errors.append("查看窗口 lookback_hours 需在 1～336 小时")
    if backfill < 1 or backfill > 24 * 30:
        errors.append("回算窗口 backfill_hours 需在 1～720 小时")
    return {"valid": len(errors) == 0, "errors": errors}


def validate_agg_field(mapping: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    category = str(mapping.get("field_category") or "").strip().lower()
    target = str(mapping.get("target_field") or "").strip()
    if not target:
        errors.append("缺少目标字段 target_field")
    elif len(target) > 100:
        errors.append(f"目标字段名过长: {target}")
    if category not in _AGG_CATEGORIES:
        errors.append(f"不支持的 field_category: {category or '?'}")

    if category == "dimension":
        source = str(mapping.get("source_field") or "").strip()
        if not source:
            errors.append(f"维度必须提供 source_field（目标 {target or '?'}）")
    elif category == "measure":
        func = str(mapping.get("aggregate_func") or "COUNT").strip().upper()
        if func not in _AGG_FUNCS:
            errors.append(f"不支持的聚合函数: {func}")
        source = str(mapping.get("source_field") or "").strip()
        if func != "COUNT" and not source:
            errors.append(f"{func} 必须提供 source_field（目标 {target or '?'}）")
    elif category == "derived":
        formula = str(mapping.get("formula") or "").strip()
        if not formula:
            errors.append(f"派生字段必须提供 formula（目标 {target or '?'}）")
        elif not is_safe_sql_expression(formula):
            errors.append(f"公式不安全或非法: {target or '?'}")
    return {"valid": len(errors) == 0, "errors": errors}


def validate_agg_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if not fields:
        errors.append("请至少配置一个维度或度量")
        return {"valid": False, "errors": errors}

    seen: set[str] = set()
    has_measure = False
    for idx, item in enumerate(fields):
        row = item if isinstance(item, dict) else {}
        result = validate_agg_field(row)
        for err in result["errors"]:
            errors.append(f"第 {idx + 1} 列: {err}")
        target = str(row.get("target_field") or "").strip().lower()
        if target:
            if target in seen:
                errors.append(f"目标字段重复: {row.get('target_field')}")
            seen.add(target)
        if str(row.get("field_category") or "").strip().lower() == "measure":
            has_measure = True
    if not has_measure:
        errors.append("请至少配置一个度量（如 COUNT 产量）")
    return {"valid": len(errors) == 0, "errors": errors}


def validate_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    if not fields:
        errors.append("请先配置至少一个字段映射")
        return {"valid": False, "errors": errors}

    seen: set[str] = set()
    for idx, item in enumerate(fields):
        result = validate_field_mapping(item if isinstance(item, dict) else {})
        for err in result["errors"]:
            errors.append(f"第 {idx + 1} 列: {err}")
        target = str((item or {}).get("target_field") or "").strip().lower()
        if target:
            if target in seen:
                errors.append(f"目标字段重复: {(item or {}).get('target_field')}")
            seen.add(target)
    return {"valid": len(errors) == 0, "errors": errors}
