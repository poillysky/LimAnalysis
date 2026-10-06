"""按项目、维度筛选 ADS，按小时汇总不良率（SUM(不良)/SUM(产量)，不用小时率再平均）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect, text

from app.core import db as stores
from app.core.projects import get_project, load_projects
from app.core.sql_ident import ident, q

DIMS = (
    ("line", "自动外观线体", "线体"),
    ("machine", "机台", "机台"),
    ("cavity", "模穴", "穴位"),
    ("core", "模仁", "模仁"),
)
_DIM_COL = {key: col for key, col, _ in DIMS}

# 交叉表窗口：近 1 小时 / 3 小时 / 1 天 / 3 天
_MAX_CAVITY_HOURS = 72

_APPEARANCE_ITEMS = (
    "外长直边",
    "正面硅胶",
    "内长直边",
    "反面烟囱",
    "正面支架",
    "反面边框",
    "硅胶短边",
)
_MOLD_ITEMS = (
    "B5合模线溢胶",
    "B1缺胶气泡",
    "B2凹坑",
    "底涂",
    "硅胶",
    "定位",
)


def _defect_item(column: str) -> str | None:
    col = ident(column)
    if not col.endswith("不良数"):
        return None
    if "总不良" in col:
        return None
    return col[: -len("不良数")]


def _defect_family(item: str) -> str:
    if item in _APPEARANCE_ITEMS:
        return "外观"
    if item in _MOLD_ITEMS:
        return "注塑"
    return "外观"


def _prefix(project: dict) -> str:
    return str(project.get("prefix") or project.get("project_id") or "").strip()


def _ads_table(prefix: str) -> str:
    return ident(f"{prefix}_ads")


def _window_hours(hours: int | None, default: int = 3) -> int:
    try:
        value = int(hours if hours is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(_MAX_CAVITY_HOURS, value))


def _dwh_tables() -> set[str]:
    return set(inspect(stores.dwh_engine).get_table_names())


def _enabled_project(project_id: str | None) -> tuple[list[dict], dict | None]:
    projects = [p for p in load_projects() if p.get("enabled", True)]
    chosen = None
    if project_id:
        chosen = next((p for p in projects if p.get("project_id") == project_id), None)
        if chosen is None:
            raise ValueError("项目不存在")
    elif projects:
        chosen = projects[0]
    return projects, chosen


def _clean_filter(value: str | None) -> str:
    return str(value or "").strip()


def _filter_map(
    *,
    line: str | None = None,
    machine: str | None = None,
    cavity: str | None = None,
    core: str | None = None,
) -> dict[str, str]:
    raw = {
        "line": _clean_filter(line),
        "machine": _clean_filter(machine),
        "cavity": _clean_filter(cavity),
        "core": _clean_filter(core),
    }
    return {k: v for k, v in raw.items() if v}


def _where(filters: dict[str, str], *, skip: str | None = None) -> tuple[str, dict]:
    clauses = []
    params: dict = {}
    for key, value in filters.items():
        if key == skip:
            continue
        col = _DIM_COL.get(key)
        if not col:
            continue
        pname = f"f_{key}"
        clauses.append(f"BTRIM({q(ident(col))}) = :{pname}")
        params[pname] = value
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _hour_label(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:00")
    text = str(value).replace("T", " ")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00")[:32])
        return stamp.strftime("%m-%d %H:00")
    except ValueError:
        return text[:16]


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _table_columns(table: str) -> list[str]:
    try:
        return [str(c["name"]) for c in inspect(stores.dwh_engine).get_columns(table)]
    except Exception:
        return []


def _metrics(table: str) -> list[dict]:
    cols = _table_columns(table)
    items: list[dict] = []
    if "自动外观总产量" in cols and "自动外观总不良数" in cols:
        items.append({"key": "appearance", "label": "自动外观不良率"})
    if "注塑机总产量" in cols and "注塑机总不良数" in cols:
        items.append({"key": "mold", "label": "注塑机不良率"})
    for col in cols:
        name = _defect_item(col)
        if name:
            items.append({"key": f"defect:{name}", "label": f"{name}不良率"})
    return items


def _distinct(table: str, column: str, filters: dict[str, str], skip: str) -> list[str]:
    where, params = _where(filters, skip=skip)
    sql = (
        f"SELECT DISTINCT BTRIM({q(ident(column))}) AS v "
        f"FROM {q(table)}{where}"
    )
    extra = f"BTRIM({q(ident(column))}) <> ''"
    sql += (" AND " if where else " WHERE ") + extra
    sql += " ORDER BY 1"
    with stores.dwh_engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [str(r[0]) for r in rows if r[0] not in (None, "")]


def list_query_catalog(
    project_id: str | None = None,
    *,
    line: str | None = None,
    machine: str | None = None,
    cavity: str | None = None,
    core: str | None = None,
) -> dict:
    projects, chosen = _enabled_project(project_id)
    if chosen is None:
        return {
            "projects": [],
            "current": None,
            "ready": False,
            "dims": {key: [] for key, _, _ in DIMS},
            "dim_fields": [{"key": k, "column": c, "label": lab} for k, c, lab in DIMS],
            "metrics": [],
        }
    prefix = _prefix(chosen)
    table = _ads_table(prefix)
    ready = table in _dwh_tables()
    filters = _filter_map(line=line, machine=machine, cavity=cavity, core=core)
    dims = {key: [] for key, _, _ in DIMS}
    if ready:
        for key, col, _ in DIMS:
            dims[key] = _distinct(table, col, filters, key)
    return {
        "projects": [
            {"project_id": p["project_id"], "display_name": p["display_name"]}
            for p in projects
        ],
        "current": {
            "project_id": chosen["project_id"],
            "display_name": chosen["display_name"],
            "prefix": prefix,
        },
        "ready": ready,
        "table": table if ready else "",
        "dims": dims,
        "dim_fields": [{"key": k, "column": c, "label": lab} for k, c, lab in DIMS],
        "metrics": _metrics(table) if ready else [],
    }


def _metric_spec(metric: str) -> tuple[str, str, str, str | None]:
    """返回 (key, label, qty_col, ng_col)。ng_col 为宽表不良数列名。"""
    key = str(metric or "appearance").strip() or "appearance"
    if key == "appearance":
        return "appearance", "自动外观不良率", "自动外观总产量", "自动外观总不良数"
    if key == "mold":
        return "mold", "注塑机不良率", "注塑机总产量", "注塑机总不良数"
    if key.startswith("defect:"):
        item = key.split(":", 1)[1].strip()
        if not item:
            raise ValueError("未知指标")
        family = _defect_family(item)
        qty_col = "注塑机总产量" if family == "注塑" else "自动外观总产量"
        return key, f"{item}不良率", qty_col, f"{item}不良数"
    raise ValueError("未知指标")


def _series_scope(
    *,
    cavity_letter: str | None = None,
    body_mold: str | None = None,
    body_cavity: str | None = None,
    cols: set[str],
) -> tuple[str, dict]:
    """交叉表一格对应的历史曲线范围：机台×模穴字母，或本体模具×穴位。"""
    clauses: list[str] = []
    params: dict = {}
    letter = str(cavity_letter or "").strip().upper()
    if letter:
        if "模穴" not in cols:
            raise ValueError("ADS 缺少列：模穴")
        if len(letter) != 1 or not letter.isalpha():
            raise ValueError("模穴字母无效")
        cav = f"BTRIM({q(ident('模穴'))})"
        clauses.append(f"UPPER(RIGHT({cav}, 1)) = :cavity_letter")
        params["cavity_letter"] = letter
    mold = str(body_mold or "").strip()
    cavity = str(body_cavity or "").strip().upper()
    if cavity in _BODY_LETTER_TO_DIGIT:
        cavity = _BODY_LETTER_TO_DIGIT[cavity]
    if mold or cavity:
        if "本体" not in cols:
            raise ValueError("ADS 缺少列：本体")
        body = f"BTRIM({q(ident('本体'))})"
        clauses.append(f"CHAR_LENGTH({body}) >= 2")
        if mold:
            if not (len(mold) == 1 and mold.isdigit()):
                raise ValueError("本体模具号无效")
            clauses.append(f"SUBSTRING({body} FROM 1 FOR 1) = :body_mold")
            params["body_mold"] = mold
        else:
            clauses.append(f"SUBSTRING({body} FROM 1 FOR 1) ~ '^[0-9]$'")
        if cavity:
            if cavity not in "12345678":
                raise ValueError("本体穴位无效")
            clauses.append(f"SUBSTRING({body} FROM 2 FOR 1) = :body_cavity")
            params["body_cavity"] = cavity
        else:
            clauses.append(f"SUBSTRING({body} FROM 2 FOR 1) ~ '^[1-8]$'")
    if not clauses:
        return "", {}
    return " AND " + " AND ".join(clauses), params


def query_series(
    project_id: str,
    *,
    metric: str = "appearance",
    line: str | None = None,
    machine: str | None = None,
    cavity: str | None = None,
    core: str | None = None,
    cavity_letter: str | None = None,
    body_mold: str | None = None,
    body_cavity: str | None = None,
) -> dict:
    project = get_project(project_id)
    if project is None or not project.get("enabled", True):
        raise ValueError("项目不存在")
    prefix = _prefix(project)
    table = _ads_table(prefix)
    if table not in _dwh_tables():
        raise ValueError(f"还没有 ADS 表（{table}）")
    mkey, mlabel, qty_col, ng_col = _metric_spec(metric)
    cols = set(_table_columns(table))
    if qty_col not in cols or ng_col not in cols:
        raise ValueError(f"ADS 缺少列：{qty_col} / {ng_col}")
    filters = _filter_map(line=line, machine=machine, cavity=cavity, core=core)
    where, params = _where(filters)
    extra_sql, extra_params = _series_scope(
        cavity_letter=cavity_letter,
        body_mold=body_mold,
        body_cavity=body_cavity,
        cols=cols,
    )
    if extra_sql:
        where = (where + extra_sql) if where else (" WHERE 1=1" + extra_sql)
        params.update(extra_params)
        if cavity_letter:
            filters["cavity_letter"] = str(cavity_letter).strip().upper()
        if body_mold:
            filters["body_mold"] = str(body_mold).strip()
        if body_cavity:
            filters["body_cavity"] = str(body_cavity).strip().upper()

    hour_sql = q(ident("hour"))
    qty_sql, ng_sql = q(ident(qty_col)), q(ident(ng_col))
    sql = (
        f"SELECT {hour_sql} AS hour, "
        f"SUM({qty_sql}) AS qty, "
        f"SUM({ng_sql}) AS ng "
        f"FROM {q(table)}{where} "
        f"GROUP BY {hour_sql} "
        f"ORDER BY {hour_sql}"
    )
    with stores.dwh_engine.connect() as conn:
        records = conn.execute(text(sql), params).fetchall()

    rows = []
    for rec in records:
        qty = _as_float(rec[1]) or 0.0
        ng = _as_float(rec[2]) or 0.0
        rate = (ng / qty) if qty > 0 else None
        rows.append(
            {
                "hour": str(rec[0]) if rec[0] is not None else "",
                "hour_label": _hour_label(rec[0]),
                "qty": qty,
                "ng": ng,
                "rate": rate,
                "rate_pct": None if rate is None else round(rate * 100, 2),
            }
        )
    return {
        "project_id": project_id,
        "metric": mkey,
        "metric_label": mlabel,
        "filters": filters,
        "rows": rows,
        "total": len(rows),
    }


def _cavity_ctx(
    project_id: str,
    *,
    hours: int,
    metric: str,
    extra_cols: tuple[str, ...],
) -> dict:
    window = _window_hours(hours)
    project = get_project(project_id)
    if project is None or not project.get("enabled", True):
        raise ValueError("项目不存在")
    prefix = _prefix(project)
    table = _ads_table(prefix)
    if table not in _dwh_tables():
        raise ValueError(f"还没有 ADS 表（{table}）")
    mkey, mlabel, qty_col, ng_col = _metric_spec(metric)
    cols = set(_table_columns(table))
    for need in (qty_col, ng_col, "hour", *extra_cols):
        if need not in cols:
            raise ValueError(f"ADS 缺少列：{need}")
    return {
        "window": window,
        "table": table,
        "qty_col": qty_col,
        "ng_col": ng_col,
        "mkey": mkey,
        "mlabel": mlabel,
    }


def _clean_codes(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _parse_pairs(values) -> list[tuple[str, str]]:
    """解析 entity:cavity 对，如 D6:A 或 5:3。"""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in _clean_codes(values):
        if ":" not in raw:
            continue
        left, right = raw.split(":", 1)
        entity = left.strip()
        cavity = right.strip().upper()
        if not entity or not cavity:
            continue
        key = (entity, cavity)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


_BODY_LETTER_TO_DIGIT = {
    "A": "1",
    "B": "2",
    "C": "3",
    "D": "4",
    "E": "5",
    "F": "6",
    "G": "7",
    "H": "8",
}


def _exclude_machine_cavity_sql(pairs) -> tuple[str, dict]:
    """排除机台 × 模穴字母格子：对应 ADS 行的产量/不良都不进汇总。"""
    items = _parse_pairs(pairs)
    if not items:
        return "", {}
    machine_sql = f"BTRIM({q(ident('机台'))})"
    cavity_sql = f"BTRIM({q(ident('模穴'))})"
    letter_sql = f"UPPER(SUBSTRING({cavity_sql} FROM CHAR_LENGTH({cavity_sql}) FOR 1))"
    clauses: list[str] = []
    params: dict = {}
    for i, (machine, letter) in enumerate(items):
        if len(letter) != 1 or not letter.isalpha():
            continue
        mkey, ckey = f"xmc_m_{i}", f"xmc_c_{i}"
        clauses.append(f"({machine_sql} = :{mkey} AND {letter_sql} = :{ckey})")
        params[mkey] = machine
        params[ckey] = letter
    if not clauses:
        return "", {}
    return f" AND NOT ({' OR '.join(clauses)})", params


def _exclude_body_cavity_sql(pairs) -> tuple[str, dict]:
    """排除本体模具 × 穴位（第 2 位 1–8 或 A–H）：对应 ADS 行不进汇总。"""
    items = _parse_pairs(pairs)
    if not items:
        return "", {}
    body_sql = f"BTRIM({q(ident('本体'))})"
    mold_sql = f"SUBSTRING({body_sql} FROM 1 FOR 1)"
    digit_sql = f"SUBSTRING({body_sql} FROM 2 FOR 1)"
    clauses: list[str] = []
    params: dict = {}
    for i, (mold, cavity) in enumerate(items):
        digit = cavity
        if digit in _BODY_LETTER_TO_DIGIT:
            digit = _BODY_LETTER_TO_DIGIT[digit]
        if not mold.isdigit() or digit not in "12345678":
            continue
        mkey, dkey = f"xbc_m_{i}", f"xbc_d_{i}"
        clauses.append(f"({mold_sql} = :{mkey} AND {digit_sql} = :{dkey})")
        params[mkey] = mold
        params[dkey] = digit
    if not clauses:
        return "", {}
    return f" AND NOT ({' OR '.join(clauses)})", params


def _query_dim_cavity(
    project_id: str,
    *,
    dim_col: str,
    dim_key: str,
    hours: int = 3,
    metric: str = "appearance",
    exclude_machine_cavities=None,
    exclude_body_cavities=None,
) -> dict:
    """近 N 小时（含最新小时桶）按维度 × 模穴汇总所选不良指标。"""
    extra = [dim_col, "模穴"]
    if _parse_pairs(exclude_body_cavities):
        extra.append("本体")
    ctx = _cavity_ctx(
        project_id, hours=hours, metric=metric, extra_cols=tuple(extra)
    )
    window = ctx["window"]
    table = ctx["table"]
    hour_sql = q(ident("hour"))
    dim_sql = q(ident(dim_col))
    cavity_sql = q(ident("模穴"))
    qty_sql, ng_sql = q(ident(ctx["qty_col"])), q(ident(ctx["ng_col"]))
    machine_excl, machine_params = _exclude_machine_cavity_sql(
        exclude_machine_cavities
    )
    body_excl, body_params = _exclude_body_cavity_sql(exclude_body_cavities)
    sql = (
        f"WITH bounds AS ("
        f"  SELECT MAX({hour_sql}) AS hi FROM {q(table)}"
        f") "
        f"SELECT BTRIM({dim_sql}) AS {dim_key}, "
        f"BTRIM({cavity_sql}) AS cavity, "
        f"SUM({qty_sql}) AS qty, "
        f"SUM({ng_sql}) AS ng, "
        f"MIN({hour_sql}) AS lo, "
        f"MAX({hour_sql}) AS hi "
        f"FROM {q(table)}, bounds "
        f"WHERE bounds.hi IS NOT NULL "
        f"AND {hour_sql} >= bounds.hi - (:hours - 1) * INTERVAL '1 hour' "
        f"AND BTRIM({dim_sql}) <> '' "
        f"AND BTRIM({cavity_sql}) <> '' "
        f"{machine_excl}{body_excl} "
        f"GROUP BY BTRIM({dim_sql}), BTRIM({cavity_sql}) "
        f"ORDER BY BTRIM({dim_sql}), BTRIM({cavity_sql})"
    )
    params = {"hours": window, **machine_params, **body_params}
    with stores.dwh_engine.connect() as conn:
        records = conn.execute(text(sql), params).fetchall()

    rows = []
    win_lo = win_hi = None
    for rec in records:
        qty = _as_float(rec[2]) or 0.0
        ng = _as_float(rec[3]) or 0.0
        rate = (ng / qty) if qty > 0 else None
        if rec[4] is not None and (win_lo is None or rec[4] < win_lo):
            win_lo = rec[4]
        if rec[5] is not None and (win_hi is None or rec[5] > win_hi):
            win_hi = rec[5]
        rows.append(
            {
                dim_key: str(rec[0] or ""),
                "cavity": str(rec[1] or ""),
                "qty": qty,
                "ng": ng,
                "rate": rate,
                "rate_pct": None if rate is None else round(rate * 100, 2),
            }
        )
    return {
        "project_id": project_id,
        "metric": ctx["mkey"],
        "metric_label": ctx["mlabel"],
        "dim": dim_key,
        "dim_label": dim_col,
        "hours": window,
        "from_hour": _hour_label(win_lo),
        "to_hour": _hour_label(win_hi),
        "rows": rows,
        "total": len(rows),
    }


def query_machine_cavity(
    project_id: str,
    *,
    hours: int = 3,
    metric: str = "appearance",
    exclude_machine_cavities=None,
    exclude_body_cavities=None,
) -> dict:
    """近 N 小时（含最新小时桶）按机台 × 模穴汇总所选不良指标。"""
    return _query_dim_cavity(
        project_id,
        dim_col="机台",
        dim_key="machine",
        hours=hours,
        metric=metric,
        exclude_machine_cavities=exclude_machine_cavities,
        exclude_body_cavities=exclude_body_cavities,
    )


def query_machine_cavity_breakdown(
    project_id: str,
    *,
    hours: int = 3,
) -> dict:
    """近 N 小时按机台 × 模穴汇总外观不良，并带上各不良项件数。"""
    ctx = _cavity_ctx(
        project_id, hours=hours, metric="appearance", extra_cols=("机台", "模穴")
    )
    cols = set(_table_columns(ctx["table"]))
    items = []
    seen: set[str] = set()
    for col in _table_columns(ctx["table"]):
        name = _defect_item(col)
        if not name or name in seen or f"{name}不良数" not in cols:
            continue
        if str(name).strip() in _APPEARANCE_ITEMS:
            continue
        seen.add(name)
        items.append(name)
    window = ctx["window"]
    table = ctx["table"]
    hour_sql = q(ident("hour"))
    machine_sql = q(ident("机台"))
    cavity_sql = q(ident("模穴"))
    qty_sql, ng_sql = q(ident(ctx["qty_col"])), q(ident(ctx["ng_col"]))
    extra_select = "".join(
        f', COALESCE(SUM({q(ident(f"{name}不良数"))}), 0) AS d_{i}'
        for i, name in enumerate(items)
    )
    sql = (
        f"WITH bounds AS ("
        f"  SELECT MAX({hour_sql}) AS hi FROM {q(table)}"
        f") "
        f"SELECT BTRIM({machine_sql}) AS machine, "
        f"BTRIM({cavity_sql}) AS cavity, "
        f"SUM({qty_sql}) AS qty, "
        f"SUM({ng_sql}) AS ng, "
        f"MIN({hour_sql}) AS lo, "
        f"MAX({hour_sql}) AS hi"
        f"{extra_select} "
        f"FROM {q(table)}, bounds "
        f"WHERE bounds.hi IS NOT NULL "
        f"AND {hour_sql} >= bounds.hi - (:hours - 1) * INTERVAL '1 hour' "
        f"AND BTRIM({machine_sql}) <> '' "
        f"AND BTRIM({cavity_sql}) <> '' "
        f"GROUP BY BTRIM({machine_sql}), BTRIM({cavity_sql}) "
        f"ORDER BY BTRIM({machine_sql}), BTRIM({cavity_sql})"
    )
    with stores.dwh_engine.connect() as conn:
        records = conn.execute(text(sql), {"hours": window}).fetchall()

    rows = []
    win_lo = win_hi = None
    for rec in records:
        qty = _as_float(rec[2]) or 0.0
        ng = _as_float(rec[3]) or 0.0
        rate = (ng / qty) if qty > 0 else None
        if rec[4] is not None and (win_lo is None or rec[4] < win_lo):
            win_lo = rec[4]
        if rec[5] is not None and (win_hi is None or rec[5] > win_hi):
            win_hi = rec[5]
        defects = []
        for i, name in enumerate(items):
            count = _as_float(rec[6 + i]) or 0.0
            if count <= 0:
                continue
            defects.append(
                {
                    "item": name,
                    "label": name,
                    "ng": count,
                }
            )
        defects.sort(key=lambda item: -item["ng"])
        rows.append(
            {
                "machine": str(rec[0] or ""),
                "cavity": str(rec[1] or ""),
                "qty": qty,
                "ng": ng,
                "rate": rate,
                "rate_pct": None if rate is None else round(rate * 100, 2),
                "defects": defects,
                "reasons": [item["label"] for item in defects],
            }
        )
    return {
        "project_id": project_id,
        "hours": window,
        "from_hour": _hour_label(win_lo),
        "to_hour": _hour_label(win_hi),
        "rows": rows,
        "total": len(rows),
    }


def query_body_cavity(
    project_id: str,
    *,
    hours: int = 3,
    metric: str = "appearance",
    exclude_machine_cavities=None,
    exclude_body_cavities=None,
) -> dict:
    """近 N 小时按本体码拆分：第 1 位模具 × 第 2 位穴位 1–8。"""
    extra = ["本体"]
    if _parse_pairs(exclude_machine_cavities):
        extra.append("机台")
        extra.append("模穴")
    ctx = _cavity_ctx(
        project_id, hours=hours, metric=metric, extra_cols=tuple(dict.fromkeys(extra))
    )
    window = ctx["window"]
    table = ctx["table"]
    hour_sql = q(ident("hour"))
    body_sql = q(ident("本体"))
    mold_sql = f"SUBSTRING(BTRIM({body_sql}) FROM 1 FOR 1)"
    cavity_sql = f"SUBSTRING(BTRIM({body_sql}) FROM 2 FOR 1)"
    qty_sql, ng_sql = q(ident(ctx["qty_col"])), q(ident(ctx["ng_col"]))
    machine_excl, machine_params = _exclude_machine_cavity_sql(
        exclude_machine_cavities
    )
    body_excl, body_params = _exclude_body_cavity_sql(exclude_body_cavities)
    sql = (
        f"WITH bounds AS ("
        f"  SELECT MAX({hour_sql}) AS hi FROM {q(table)}"
        f") "
        f"SELECT {mold_sql} AS body, "
        f"{cavity_sql} AS cavity, "
        f"SUM({qty_sql}) AS qty, "
        f"SUM({ng_sql}) AS ng, "
        f"MIN({hour_sql}) AS lo, "
        f"MAX({hour_sql}) AS hi "
        f"FROM {q(table)}, bounds "
        f"WHERE bounds.hi IS NOT NULL "
        f"AND {hour_sql} >= bounds.hi - (:hours - 1) * INTERVAL '1 hour' "
        f"AND CHAR_LENGTH(BTRIM({body_sql})) >= 2 "
        f"AND {mold_sql} ~ '^[0-9]$' "
        f"AND {cavity_sql} ~ '^[1-8]$' "
        f"{machine_excl}{body_excl} "
        f"GROUP BY {mold_sql}, {cavity_sql} "
        f"ORDER BY {mold_sql}, {cavity_sql}"
    )
    params = {"hours": window, **machine_params, **body_params}
    with stores.dwh_engine.connect() as conn:
        records = conn.execute(text(sql), params).fetchall()

    rows = []
    win_lo = win_hi = None
    for rec in records:
        qty = _as_float(rec[2]) or 0.0
        ng = _as_float(rec[3]) or 0.0
        rate = (ng / qty) if qty > 0 else None
        if rec[4] is not None and (win_lo is None or rec[4] < win_lo):
            win_lo = rec[4]
        if rec[5] is not None and (win_hi is None or rec[5] > win_hi):
            win_hi = rec[5]
        rows.append(
            {
                "body": str(rec[0] or ""),
                "cavity": str(rec[1] or ""),
                "qty": qty,
                "ng": ng,
                "rate": rate,
                "rate_pct": None if rate is None else round(rate * 100, 2),
            }
        )
    return {
        "project_id": project_id,
        "metric": ctx["mkey"],
        "metric_label": ctx["mlabel"],
        "dim": "body",
        "dim_label": "本体",
        "hours": window,
        "from_hour": _hour_label(win_lo),
        "to_hour": _hour_label(win_hi),
        "rows": rows,
        "total": len(rows),
    }
