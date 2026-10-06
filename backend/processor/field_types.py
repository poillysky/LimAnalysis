"""清洗字段基础类型（对齐车间配置用语）。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from app.core.sql_ident import ident, q

# value 存库；label 给前端
FIELD_TYPES: list[dict[str, str]] = [
    {"value": "text", "label": "文本"},
    {"value": "integer", "label": "整数"},
    {"value": "decimal", "label": "小数"},
    {"value": "percent", "label": "百分比"},
    {"value": "datetime", "label": "时间"},
    {"value": "boolean", "label": "布尔"},
]

ALLOWED_TYPES = {item["value"] for item in FIELD_TYPES}

# 车间维度/编码类：取值可能是 "1"/"A"，但本质是文本，绝不当布尔
_TEXT_DIM_RE = re.compile(
    r"("
    r"线体|产线|line\b|机台|设备|工站|工序|站点|station|"
    r"模具|模穴|模仁|穴号|机种|料号|批次|批号|lot|batch|"
    r"前盖码|条码|二维码|\bsn\b|serial|编码|代号|班次|班组|人员|操作员"
    r")",
    re.I,
)

_TIME_RE = re.compile(
    r"(时间|日期|时刻|timestamp|datetime|_time$|_date$|_at$|servertime|upload|ingested)",
    re.I,
)
_PERCENT_RE = re.compile(r"(百分比|百分|合格率|不良率|rate|percent|pct|%)", re.I)
_INT_RE = re.compile(r"(次数|计数|数量|个数|count|qty|num$|_n$|序号)", re.I)
_DEC_RE = re.compile(
    r"(直径|长度|宽度|高度|厚度|温度|压力|速度|重量|尺寸|距离|毫米|数值|value)",
    re.I,
)
# 明确结果/判定列
_BOOL_RE = re.compile(
    r"(结果|是否|判定|ok|ng|pass|fail|boolean|bool|flag|合格|不良)",
    re.I,
)
# 缺陷/点检类 0/1 列（无「结果」字样）
_DEFECT_BOOL_RE = re.compile(
    r"("
    r"气泡|缺胶|溢胶|破损|铲伤|压伤|毛边|凹坑|呆料|合模|"
    r"底涂|试模|定位|短路|变形|脏污|刮伤|裂|伤|胶"
    r")",
    re.I,
)
# 点检项简码：B1、B2、C3。仅在取值为 0/1 时当布尔，避免把模穴编码当结果
_INSPECT_CODE_RE = re.compile(r"^[A-Za-z]\d{1,2}$")

_BOOL_TRUE = frozenset({"1", "true", "t", "y", "yes", "ok", "pass", "合格", "通过"})
_BOOL_FALSE = frozenset({"0", "false", "f", "n", "no", "ng", "fail", "不合格", "失败"})
_BOOL_ALL = _BOOL_TRUE | _BOOL_FALSE
_BOOL_WORD = _BOOL_ALL - {"0", "1"}

_INT_VAL_RE = re.compile(r"^-?\d+(\.0+)?$")
_DEC_VAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_PCT_VAL_RE = re.compile(r"^-?\d+(\.\d+)?%?$")
_TIME_VAL_RE = re.compile(
    r"^("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
    r"|"
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r")$"
)


def normalize_field_type(value: str | None) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "string": "text",
        "str": "text",
        "文本": "text",
        "int": "integer",
        "整数": "integer",
        "float": "decimal",
        "number": "decimal",
        "小数": "decimal",
        "百分比": "percent",
        "pct": "percent",
        "time": "datetime",
        "date": "datetime",
        "timestamp": "datetime",
        "时间": "datetime",
        "日期": "datetime",
        "布尔": "boolean",
        "bool": "boolean",
    }
    text = aliases.get(text, text)
    return text if text in ALLOWED_TYPES else "text"


def _norm_sample(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _name_suggests_boolean(column_name: str) -> bool:
    name = str(column_name or "")
    if _TEXT_DIM_RE.search(name):
        return False
    if _DEC_RE.search(name) and not _BOOL_RE.search(name):
        return False
    return bool(_BOOL_RE.search(name) or _DEFECT_BOOL_RE.search(name))


def _samples_look_boolean(uniq_lower: set[str], column_name: str) -> bool:
    """0/1  alone 不够；需双边取值、布尔词，或列名像结果/缺陷。"""
    if not uniq_lower or not uniq_lower <= _BOOL_ALL:
        return False
    has_true = bool(uniq_lower & _BOOL_TRUE)
    has_false = bool(uniq_lower & _BOOL_FALSE)
    has_word = bool(uniq_lower & _BOOL_WORD)
    if has_word:
        return True
    if has_true and has_false:
        return True
    # 仅单边 0 或 1：只有列名像判定/缺陷/点检简码才当布尔（线体=1 不会进来）
    if _name_suggests_boolean(column_name):
        return True
    return bool(_INSPECT_CODE_RE.match(str(column_name or "").strip()))


def guess_field_type_from_samples(
    column_name: str, samples: Iterable | None = None
) -> str:
    """列名规则 + 采样值联合推断。

    - 线体/机台/工站/码 等维度 → 文本（即使取值是 1）
    - 结果/缺陷列且为 0/1、OK/NG → 布尔
    - 时间列 / 时间戳采样 → 时间
    """
    name = str(column_name or "")

    # 1) 强列名优先
    if _TEXT_DIM_RE.search(name):
        return "text"
    if _TIME_RE.search(name):
        return "datetime"
    if _PERCENT_RE.search(name):
        return "percent"

    values: list[str] = []
    for raw in samples or []:
        text = _norm_sample(raw)
        if text is not None:
            values.append(text)

    if values:
        lower = [v.lower() for v in values]
        uniq = set(lower)

        if all(_TIME_VAL_RE.match(v) for v in values):
            return "datetime"

        if _samples_look_boolean(uniq, name):
            return "boolean"

        if any("%" in v for v in values) and all(
            _PCT_VAL_RE.match(v.replace(" ", "")) for v in values
        ):
            return "percent"

        # 纯 0/1 但未判定为布尔 → 不当整数，回退列名（多为文本编码）
        if uniq <= {"0", "1"}:
            return guess_field_type(name)

        if all(_INT_VAL_RE.match(v) for v in values):
            return "integer"

        if all(_DEC_VAL_RE.match(v) for v in values):
            return "decimal"

    return guess_field_type(name)


def guess_field_types_for_table(
    columns: Sequence[str],
    sample_rows: Sequence[Mapping | Sequence] | None = None,
) -> dict[str, str]:
    """对整表列批量推断类型。"""
    by_col: dict[str, list] = {c: [] for c in columns}
    for row in sample_rows or []:
        if isinstance(row, Mapping):
            for col in columns:
                by_col[col].append(row.get(col))
        else:
            for idx, col in enumerate(columns):
                if idx < len(row):
                    by_col[col].append(row[idx])
    return {
        col: guess_field_type_from_samples(col, by_col.get(col))
        for col in columns
    }


def guess_field_type(column_name: str) -> str:
    name = str(column_name or "")
    if _TEXT_DIM_RE.search(name):
        return "text"
    if _TIME_RE.search(name):
        return "datetime"
    if _PERCENT_RE.search(name):
        return "percent"
    if _name_suggests_boolean(name):
        return "boolean"
    if _INT_RE.search(name):
        return "integer"
    if _DEC_RE.search(name):
        return "decimal"
    return "text"


def sql_blank_as_null(src_sql: str) -> str:
    """空串、空白当成 SQL NULL；原表 NULL 保持 NULL。"""
    return f"NULLIF(BTRIM({src_sql}), '')"


def pg_type_for_field_type(field_type: str) -> str:
    """ETL field_type → PostgreSQL 列类型（DWD/ADS 写入用）。"""
    ftype = normalize_field_type(field_type)
    return {
        "integer": "BIGINT",
        "decimal": "NUMERIC",
        "percent": "NUMERIC",
        "datetime": "TIMESTAMPTZ",
        "boolean": "SMALLINT",
        "text": "TEXT",
    }.get(ftype, "TEXT")


def coerce_sql_to_field_type(inner_sql: str, field_type: str) -> str:
    """把任意 SQL 表达式收成目标 field_type（用于 derived/constant）。"""
    ftype = normalize_field_type(field_type)
    inner = f"({inner_sql})"
    trimmed = sql_blank_as_null(f"{inner}::text")
    if ftype == "integer":
        return (
            f"CASE WHEN {trimmed} ~ '^-?\\d+(\\.0+)?$' "
            f"THEN ROUND(({trimmed})::numeric)::bigint ELSE NULL END"
        )
    if ftype == "decimal":
        return (
            f"CASE WHEN {trimmed} ~ '^-?\\d+(\\.\\d+)?$' "
            f"THEN ({trimmed})::numeric ELSE NULL END"
        )
    if ftype == "percent":
        cleaned = f"REPLACE({trimmed}, '%', '')"
        return (
            f"CASE WHEN {cleaned} ~ '^-?\\d+(\\.\\d+)?$' "
            f"THEN ({cleaned})::numeric ELSE NULL END"
        )
    if ftype == "datetime":
        return f"{trimmed}::timestamptz"
    if ftype == "boolean":
        return (
            f"CASE "
            f"WHEN lower(COALESCE({trimmed}, '')) IN "
            f"('1','true','t','y','yes','ok','pass','合格','通过') THEN 1::smallint "
            f"WHEN lower(COALESCE({trimmed}, '')) IN "
            f"('0','false','f','n','no','ng','fail','不合格','失败') THEN 0::smallint "
            f"ELSE NULL END"
        )
    return trimmed


def cast_direct_expr(source_field: str, target_field: str, field_type: str) -> str:
    """生成 direct 映射的 SELECT 表达式：从 RAW 文本清洗并落到真实 PG 类型。"""
    src = q(ident(source_field))
    tgt = ident(target_field)
    body = coerce_sql_to_field_type(src, field_type)
    return f"    {body} AS {q(tgt)}"
