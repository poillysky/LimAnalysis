"""按项目已配置连接浏览 meta / raw / dwh / defect 表数据。"""

from __future__ import annotations

import contextlib
import re

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core import db as stores

TARGETS = ("meta", "raw", "dwh", "defect")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
        rows.append({"name": name, "columns": len(cols)})
    return rows


def table_preview(
    target: str,
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
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
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {qtable}")).scalar() or 0
        result = conn.execute(
            text(f"SELECT * FROM {qtable} LIMIT :limit OFFSET :offset"),
            {"limit": limit, "offset": offset},
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
