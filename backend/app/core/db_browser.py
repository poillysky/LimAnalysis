"""按项目已配置连接浏览 meta / raw / dwh / defect 表数据。"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core import db as stores

TARGETS = ("meta", "raw", "dwh", "defect")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SQLITE_SKIP = {"sqlite_sequence"}


def _engine(target: str) -> Engine:
    if target not in TARGETS:
        raise ValueError("未知数据源")
    if target == "meta":
        return stores.meta_engine
    if target == "raw":
        return stores.raw_engine
    if target == "defect":
        return stores.defect_engine
    return stores.dwh_engine


def ensure_engines(target: str) -> None:
    """浏览只校验目标名；连接变更在「连接管理」保存时刷新引擎，避免每次查询 dispose。"""
    if target not in TARGETS:
        raise ValueError("未知数据源")
    if target == "defect":
        # 打开次品库时补齐 ServerTime 列并回填已有行
        with contextlib.suppress(Exception):
            from app.core.defect_store import ensure_defect_tables

            ensure_defect_tables()


def _quote_ident(name: str, dialect: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        raise ValueError("无效标识符")
    if dialect.startswith("sqlite"):
        if not _IDENT.match(raw):
            # SQLite 允许用双引号包一层
            return '"' + raw.replace('"', '""') + '"'
        return raw
    # postgres
    return '"' + raw.replace('"', '""') + '"'


def _pick_server_time(columns: list[str]) -> str | None:
    for name in columns:
        if name == "ServerTime":
            return name
    for name in columns:
        if str(name).lower() == "servertime":
            return name
    return None


def _parse_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1]
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"无效时间：{value}") from exc


def _time_expr(qcol: str, dialect: str) -> str:
    """兼容 TEXT / timestamptz 的 ServerTime 比较表达式。"""
    if dialect.startswith("sqlite"):
        return qcol
    return f"NULLIF(BTRIM(({qcol})::text), '')::timestamptz"


def _time_filter(
    columns: list[str],
    dialect: str,
    time_from: str | None,
    time_to: str | None,
) -> tuple[str, dict, str | None]:
    """返回 (WHERE 子句或空串, 绑定参数, 时间列名)。"""
    col = _pick_server_time(columns)
    t0 = _parse_dt(time_from)
    t1 = _parse_dt(time_to)
    if t0 is None and t1 is None:
        return "", {}, col
    if col is None:
        raise ValueError("当前表无 ServerTime 列，无法按时间筛选")
    if t0 is not None and t1 is not None and t0 > t1:
        raise ValueError("开始时间不能晚于结束时间")
    expr = _time_expr(_quote_ident(col, dialect), dialect)
    clauses: list[str] = []
    params: dict = {}
    if t0 is not None:
        clauses.append(f"{expr} >= :time_from")
        params["time_from"] = t0
    if t1 is not None:
        clauses.append(f"{expr} <= :time_to")
        params["time_to"] = t1
    return " WHERE " + " AND ".join(clauses), params, col


def list_tables(target: str) -> list[dict]:
    engine = _engine(target)
    inspector = inspect(engine)
    names = list(inspector.get_table_names())
    with contextlib.suppress(Exception):
        names.extend(inspector.get_view_names())
    rows = []
    for name in sorted(set(names)):
        try:
            cols = inspector.get_columns(name)
        except Exception:
            cols = []
        col_names = [c["name"] for c in cols]
        rows.append(
            {
                "name": name,
                "columns": len(cols),
                "time_column": _pick_server_time(col_names),
            }
        )
    return rows


def table_preview(
    target: str,
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    time_from: str | None = None,
    time_to: str | None = None,
) -> dict:
    engine = _engine(target)
    dialect = engine.dialect.name
    table = str(table or "").strip()
    if not table:
        raise ValueError("请选择表")
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with contextlib.suppress(Exception):
        existing.update(inspector.get_view_names())
    if table not in existing:
        raise ValueError("表不存在")
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    qtable = _quote_ident(table, dialect)
    columns = [c["name"] for c in inspector.get_columns(table)]
    where_sql, params, time_col = _time_filter(
        columns, dialect, time_from, time_to
    )
    order_sql = ""
    if time_col:
        order_sql = (
            f" ORDER BY {_time_expr(_quote_ident(time_col, dialect), dialect)} DESC"
        )
    with engine.connect() as conn:
        total = (
            conn.execute(
                text(f"SELECT COUNT(*) FROM {qtable}{where_sql}"), params
            ).scalar()
            or 0
        )
        result = conn.execute(
            text(
                f"SELECT * FROM {qtable}{where_sql}{order_sql} "
                f"LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        )
        keys = list(result.keys()) if result.keys() else columns
        data = []
        for row in result.mappings().all():
            item = {}
            for key in keys:
                value = row.get(key)
                if value is None:
                    item[key] = None
                elif isinstance(value, (bytes, memoryview)):
                    item[key] = f"<binary {len(value)} bytes>"
                else:
                    item[key] = str(value)
            data.append(item)
    return {
        "target": target,
        "table": table,
        "columns": keys or columns,
        "rows": data,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "time_column": time_col,
        "time_from": time_from or None,
        "time_to": time_to or None,
    }


def target_info(target: str) -> dict:
    engine = _engine(target)
    ping = stores.ping_engine(engine)
    info = {
        "target": target,
        "ok": ping["ok"],
        "error": ping["error"],
        "dialect": engine.dialect.name,
    }
    if target == "meta":
        from app.core.config import settings

        info["label"] = "元数据 SQLite"
        info["endpoint"] = str(settings.sqlite_file)
    else:
        from app.core.connections import public_connections

        pub = public_connections()[target]
        info["label"] = pub["label"]
        info["endpoint"] = f"{pub['host']}:{pub['port']} / {pub['database']}"
    return info


def _base_tables(target: str) -> list[str]:
    """仅用户表（不含视图 / sqlite 内部表）。"""
    engine = _engine(target)
    names = list(inspect(engine).get_table_names())
    return sorted(n for n in names if n not in _SQLITE_SKIP)


def _ensure_base_table(target: str, table: str) -> str:
    name = str(table or "").strip()
    if not name:
        raise ValueError("请选择表")
    if name not in set(_base_tables(target)):
        raise ValueError("只能操作数据表（视图或不存在的表不可用）")
    return name


def _write_table_csv(
    conn,
    table: str,
    dialect: str,
    *,
    time_from: str | None = None,
    time_to: str | None = None,
    columns: list[str] | None = None,
) -> bytes:
    qtable = _quote_ident(table, dialect)
    cols = columns or []
    where_sql, params, time_col = _time_filter(
        cols, dialect, time_from, time_to
    )
    order_sql = ""
    if time_col:
        order_sql = (
            f" ORDER BY {_time_expr(_quote_ident(time_col, dialect), dialect)} DESC"
        )
    result = conn.execute(
        text(f"SELECT * FROM {qtable}{where_sql}{order_sql}"), params
    )
    keys = list(result.keys())
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(keys)
    for row in result:
        out = []
        for value in row:
            if value is None:
                out.append("")
            elif isinstance(value, (bytes, memoryview)):
                out.append(f"<binary {len(value)} bytes>")
            else:
                out.append(str(value))
        writer.writerow(out)
    return buf.getvalue().encode("utf-8-sig")


def clear_table(target: str, table: str) -> dict:
    """清空指定数据表（保留表结构）。"""
    ensure_engines(target)
    if target == "meta":
        raise ValueError("元数据库禁止清空表")
    info = target_info(target)
    if not info.get("ok"):
        raise RuntimeError(info.get("error") or "数据源不可用")

    name = _ensure_base_table(target, table)
    engine = _engine(target)
    dialect = engine.dialect.name
    qtable = _quote_ident(name, dialect)
    with engine.begin() as conn:
        if dialect.startswith("sqlite"):
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.execute(text(f"DELETE FROM {qtable}"))
            with contextlib.suppress(Exception):
                conn.execute(
                    text("DELETE FROM sqlite_sequence WHERE name = :name"),
                    {"name": name},
                )
            conn.execute(text("PRAGMA foreign_keys = ON"))
        else:
            conn.execute(text(f"TRUNCATE {qtable} RESTART IDENTITY CASCADE"))

    return {
        "target": target,
        "table": name,
        "label": info.get("label") or target,
    }


def prepare_table_download(
    target: str,
    table: str,
    *,
    time_from: str | None = None,
    time_to: str | None = None,
) -> dict:
    """导出指定表为 CSV 文件；有 ServerTime 时可按时间范围导出。"""
    ensure_engines(target)
    if target == "dwh":
        raise ValueError("ETL 库禁止下载表")
    info = target_info(target)
    if not info.get("ok"):
        raise RuntimeError(info.get("error") or "数据源不可用")

    name = _ensure_base_table(target, table)
    engine = _engine(target)
    dialect = engine.dialect.name
    columns = [c["name"] for c in inspect(engine).get_columns(name)]
    time_col = _pick_server_time(columns)
    t0 = _parse_dt(time_from)
    t1 = _parse_dt(time_to)
    if time_col and (t0 is None or t1 is None):
        raise ValueError("请选择 ServerTime 起止时间后再下载")
    if time_col is None and (t0 is not None or t1 is not None):
        raise ValueError("当前表无 ServerTime 列，无法按时间筛选")

    fd, tmp_path = tempfile.mkstemp(prefix=f"lim_{target}_{name}_", suffix=".csv")
    os.close(fd)
    try:
        with engine.connect() as conn:
            data = _write_table_csv(
                conn,
                name,
                dialect,
                time_from=time_from,
                time_to=time_to,
                columns=columns,
            )
        Path(tmp_path).write_bytes(data)
    except Exception:
        with contextlib.suppress(Exception):
            os.unlink(tmp_path)
        raise

    safe = re.sub(r"[^\w.\-]+", "_", name) or "table"
    suffix = ""
    if t0 is not None and t1 is not None:
        a = t0.strftime("%Y%m%d%H%M%S")
        b = t1.strftime("%Y%m%d%H%M%S")
        suffix = f"_{a}_{b}"
    return {
        "path": tmp_path,
        "filename": f"{safe}{suffix}.csv",
        "media_type": "text/csv; charset=utf-8",
        "cleanup": True,
    }
