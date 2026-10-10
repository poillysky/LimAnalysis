import contextlib
import logging
import re
from io import StringIO

import pandas as pd
from sqlalchemy import inspect, text

from app.core.sql_ident import ident, q, table_name, unique_idents

logger = logging.getLogger(__name__)
# 多行 VALUES 一批提交；64 列 × 1000 行对 PG 仍很轻松
_BATCH = 1000

# ident / unique_idents / q / table_name 原定义在本文件，现已下沉到
# app.core.sql_ident。这里保留 re-export：`collector.runner` 等同包调用方
# 以及历史脚本仍按 `from collector.raw_loader import ident` 取用，不必全量改。
# 实现只有一份（sql_ident），这里只是别名，不存在两份实现漂移的风险。
__all__ = [
    "align_column_order",
    "decode_csv",
    "desired_column_order",
    "drop_competing_unique_indexes",
    "drop_stale_columns",
    "ensure_conflict_target",
    "ensure_table",
    "ident",
    "parse_csv",
    "purge_empty_pk_rows",
    "q",
    "relax_legacy_primary_key",
    "table_name",
    "unique_column",
    "unique_idents",
    "upsert_dataframe",
]


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def parse_csv(csv_text: str) -> pd.DataFrame:
    """
    全部按字符串读取，保留 CSV 原文（结果列 0/1 不要变成 0.0）。
    """
    common = {"dtype": str, "keep_default_na": False}
    try:
        frame = pd.read_csv(StringIO(csv_text), low_memory=False, **common)
    except Exception:
        frame = pd.read_csv(
            StringIO(csv_text), engine="python", on_bad_lines="skip", **common
        )
    frame.columns = [str(col).strip() for col in frame.columns]
    return frame


def _cell_text(value) -> str | None:
    """单元格转入库文本：整型浮点写成 0/1，空值写成 NULL。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = format(value, "g")
        return text if text else None
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    # 兜底：历史/混读产生的 "0.0" / "1.0"
    if re.fullmatch(r"-?\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def unique_column(frame: pd.DataFrame) -> str:
    from app.core.projects import load_system_defaults

    defaults = load_system_defaults()
    configured = str((defaults.get("unique_key") or {}).get("column") or "").strip()
    columns = [str(col) for col in frame.columns]
    lower_map = {col.lower(): col for col in columns}
    if configured:
        if configured in columns:
            return configured
        hit = lower_map.get(configured.lower())
        if hit:
            return hit
    return columns[0]


def _existing_columns(engine, table: str) -> list[str]:
    table_i = ident(table)
    inspector = inspect(engine)
    with contextlib.suppress(Exception):
        inspector.clear_cache()
    if not inspector.has_table(table_i):
        return []
    # 直接查 catalog，避免 SQLAlchemy 反射缓存漏掉刚变更的列
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
                ORDER BY ordinal_position
                """
            ),
            {"table": table_i},
        ).fetchall()
    if rows:
        return [str(r[0]) for r in rows]
    return [col["name"] for col in inspector.get_columns(table_i)]


def ensure_table(engine, table: str, columns: list[str], pk: str) -> None:
    quoted_table = q(table)
    existing = _existing_columns(engine, ident(table))
    if not existing:
        defs = [f"{q(pk)} TEXT PRIMARY KEY"]
        for col in columns:
            if ident(col) == ident(pk):
                continue
            defs.append(f"{q(col)} TEXT")
        defs.append("ingested_at TIMESTAMPTZ DEFAULT now()")
        sql = f"CREATE TABLE IF NOT EXISTS {quoted_table} ({', '.join(defs)})"
        with engine.begin() as conn:
            conn.execute(text(sql))
        return
    have = {ident(name) for name in existing}
    with engine.begin() as conn:
        for col in columns:
            if ident(col) in have:
                continue
            conn.execute(text(f"ALTER TABLE {quoted_table} ADD COLUMN {q(col)} TEXT"))
            have.add(ident(col))
        if "ingested_at" not in have:
            conn.execute(
                text(
                    f"ALTER TABLE {quoted_table} ADD COLUMN ingested_at TIMESTAMPTZ DEFAULT now()"
                )
            )


def drop_stale_columns(engine, table: str, columns: list[str]) -> list[str]:
    """
    删除表中不在本次 CSV 表头里的历史脏列（如早期误建的 SN/Line/col/c_*）。
    保留 ingested_at。
    """
    table_i = ident(table)
    keep = {ident(c) for c in columns}
    keep.add("ingested_at")
    existing = _existing_columns(engine, table_i)
    dropped: list[str] = []
    with engine.begin() as conn:
        for name in existing:
            if ident(name) in keep:
                continue
            conn.execute(
                text(f"ALTER TABLE {q(table_i)} DROP COLUMN IF EXISTS {q(name)} CASCADE")
            )
            dropped.append(str(name))
            logger.warning("dropped stale column %s.%s", table_i, name)
    return dropped


def purge_empty_pk_rows(engine, table: str, pk: str) -> int:
    """删除唯一键为空/空白的脏行（历史误入库会导致浏览页出现空行）。"""
    table_i = ident(table)
    pk_i = ident(pk)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                DELETE FROM {q(table_i)}
                WHERE {q(pk_i)} IS NULL
                   OR BTRIM(CAST({q(pk_i)} AS TEXT)) = ''
                """
            )
        )
        deleted = int(result.rowcount or 0)
    if deleted:
        logger.warning("purged %s empty-%s rows from %s", deleted, pk_i, table_i)
    return deleted


def desired_column_order(columns: list[str]) -> list[str]:
    """CSV 表头顺序 + ingested_at 放最后。"""
    ordered = [ident(c) for c in columns]
    if "ingested_at" not in {c.lower() for c in ordered}:
        ordered.append("ingested_at")
    return ordered


def align_column_order(engine, table: str, columns: list[str], pk: str) -> bool:
    """
    若物理列顺序与 CSV 不一致，则重建表以对齐（数据保留）。
    目标顺序：CSV 列顺序，ingested_at 在末尾。
    """
    table_i = ident(table)
    desired = desired_column_order(columns)
    existing = [ident(c) for c in _existing_columns(engine, table_i)]
    if not existing:
        return False
    if existing == desired:
        return False

    # 只搬迁 desired 中已存在的列；缺的先补过 ensure_table
    move = [c for c in desired if c in set(existing)]
    if not move:
        return False

    temp = ident(f"_ord_{table_i}")[:60]
    pk_i = ident(pk)
    defs: list[str] = []
    for col in move:
        if col == "ingested_at":
            defs.append("ingested_at TIMESTAMPTZ DEFAULT now()")
        elif col == pk_i:
            defs.append(f"{q(col)} TEXT")
        else:
            defs.append(f"{q(col)} TEXT")
    col_sql = ", ".join(q(c) for c in move)

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {q(temp)}"))
        conn.execute(text(f"CREATE TABLE {q(temp)} ({', '.join(defs)})"))
        conn.execute(
            text(
                f"INSERT INTO {q(temp)} ({col_sql}) "
                f"SELECT {col_sql} FROM {q(table_i)}"
            )
        )
        conn.execute(text(f"DROP TABLE {q(table_i)} CASCADE"))
        conn.execute(text(f'ALTER TABLE {q(temp)} RENAME TO {q(table_i)}'))
    logger.info(
        "reordered columns on %s to match CSV (%s cols)", table_i, len(move)
    )
    return True


def relax_legacy_primary_key(engine, table: str, business_pk: str) -> None:
    """
    早期用错误列（如 SN）建了主键时，CSV 只有 FCoverSN 会因 SN NOT NULL 失败。
    若当前主键不是业务唯一键，则去掉旧主键并允许旧列为空。
    """
    table_i = ident(table)
    biz = ident(business_pk)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.attname
                FROM pg_constraint co
                JOIN pg_class c ON c.oid = co.conrelid
                JOIN unnest(co.conkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE
                JOIN pg_attribute a
                  ON a.attrelid = c.oid AND a.attnum = u.attnum AND NOT a.attisdropped
                WHERE c.relname = :table AND co.contype = 'p'
                ORDER BY u.ord
                """
            ),
            {"table": table_i},
        ).fetchall()
        pk_cols = [str(r[0]) for r in rows]
        if not pk_cols or [ident(c) for c in pk_cols] == [biz]:
            return
        cons = conn.execute(
            text(
                """
                SELECT co.conname
                FROM pg_constraint co
                JOIN pg_class c ON c.oid = co.conrelid
                WHERE c.relname = :table AND co.contype = 'p'
                LIMIT 1
                """
            ),
            {"table": table_i},
        ).scalar()
        if cons:
            conn.execute(text(f"ALTER TABLE {q(table_i)} DROP CONSTRAINT {q(cons)}"))
            logger.warning(
                "dropped legacy primary key %s on %s (business key=%s)",
                cons,
                table_i,
                biz,
            )
        for col in pk_cols:
            if ident(col) == biz:
                continue
            conn.execute(
                text(f"ALTER TABLE {q(table_i)} ALTER COLUMN {q(col)} DROP NOT NULL")
            )


def drop_competing_unique_indexes(engine, table: str, pk: str) -> None:
    """
    去掉业务唯一键以外的单列 UNIQUE。
    历史误用 SerialNo/SN 建唯一索引时，ON CONFLICT(FCoverSN) 仍会撞上其它唯一约束。
    """
    table_i = ident(table)
    pk_i = ident(pk)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT i.relname AS index_name,
                       array_agg(a.attname ORDER BY u.ord) AS cols
                FROM pg_index x
                JOIN pg_class t ON t.oid = x.indrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_class i ON i.oid = x.indexrelid
                JOIN unnest(x.indkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE
                JOIN pg_attribute a
                  ON a.attrelid = t.oid AND a.attnum = u.attnum AND NOT a.attisdropped
                WHERE n.nspname = ANY (current_schemas(false))
                  AND t.relname = :table
                  AND x.indisunique
                  AND NOT x.indisprimary
                GROUP BY i.relname
                """
            ),
            {"table": table_i},
        ).fetchall()
        for index_name, cols in rows:
            col_ids = [ident(c) for c in (cols or [])]
            if col_ids == [pk_i]:
                continue
            conn.execute(text(f"DROP INDEX IF EXISTS {q(index_name)}"))
            logger.warning(
                "dropped competing unique index %s on %s (keep=%s, was=%s)",
                index_name,
                table_i,
                pk_i,
                col_ids,
            )


def ensure_conflict_target(engine, table: str, pk: str) -> None:
    """保证业务唯一列存在 UNIQUE，供 ON CONFLICT 使用。"""
    table_i = ident(table)
    pk_i = ident(pk)
    idx = ident(f"uk_{table_i}_{pk_i}")[:60]
    drop_competing_unique_indexes(engine, table, pk)
    with engine.begin() as conn:
        found = conn.execute(
            text(
                """
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = ANY (current_schemas(false))
                  AND tablename = :table
                  AND indexdef ILIKE '%UNIQUE%'
                  AND (
                    indexdef ILIKE :quoted
                    OR indexdef ILIKE :bare
                  )
                LIMIT 1
                """
            ),
            {
                "table": table_i,
                "quoted": f'%("{pk_i}")%',
                "bare": f"%({pk_i})%",
            },
        ).scalar()
        if found:
            return
        try:
            conn.execute(
                text(f"CREATE UNIQUE INDEX {q(idx)} ON {q(table_i)} ({q(pk_i)})")
            )
            logger.info("created unique index %s on %s(%s)", idx, table_i, pk_i)
        except Exception as exc:
            raise RuntimeError(
                f"无法为唯一键 {pk_i} 建立约束，请检查该列是否有重复值: {exc}"
            ) from exc


def _conflict_clause(columns: list[str], pk: str) -> str:
    updates = ", ".join(
        f"{q(col)} = EXCLUDED.{q(col)}" for col in columns if ident(col) != ident(pk)
    )
    if updates:
        return f"DO UPDATE SET {updates}, ingested_at = now()"
    return "DO UPDATE SET ingested_at = now()"


def _frame_to_value_rows(frame: pd.DataFrame, columns: list[str]) -> list[list]:
    """把 DataFrame 转成入库行（避免 iterrows）。"""
    subset = frame.loc[:, columns]
    values = subset.to_numpy(dtype=object, copy=False)
    rows: list[list] = []
    for i in range(values.shape[0]):
        row = values[i]
        rows.append([_cell_text(row[j]) for j in range(len(columns))])
    return rows


def _execute_batches(
    engine, table: str, columns: list[str], pk: str, rows: list[list]
) -> dict[str, int]:
    """
    COPY 进临时表，再一次 INSERT … SELECT … ON CONFLICT。
    返回写入/新增/更新行数（xmax=0 为新增）。
    """
    if not rows:
        return {"rows": 0, "rows_inserted": 0, "rows_updated": 0}
    col_sql = ", ".join(q(col) for col in columns)
    conflict = _conflict_clause(columns, pk)
    temp = f"_stg_{ident(table)}"[:60]
    col_defs = ", ".join(f"{q(col)} TEXT" for col in columns)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {q(temp)}")
            cur.execute(f"CREATE TEMP TABLE {q(temp)} ({col_defs}) ON COMMIT DROP")
            with cur.copy(f"COPY {q(temp)} ({col_sql}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            cur.execute(
                f"""
                INSERT INTO {q(table)} ({col_sql}, ingested_at)
                SELECT {col_sql}, now()
                FROM {q(temp)}
                ON CONFLICT ({q(pk)}) {conflict}
                RETURNING (xmax = 0) AS inserted
                """
            )
            flags = cur.fetchall()
    inserted = sum(1 for (flag,) in flags if flag)
    updated = len(flags) - inserted
    return {
        "rows": len(flags),
        "rows_inserted": inserted,
        "rows_updated": updated,
    }


def upsert_dataframe(frame: pd.DataFrame, prefix: str, project_id: str) -> dict:
    empty = {"total": 0, "unique": 0, "rows_inserted": 0, "rows_updated": 0}
    if frame.empty:
        return empty
    pk_src = unique_column(frame)
    frame = frame.copy()
    # 先丢掉空白唯一键，再 ffill，避免文件开头空行被填成脏数据
    pk_series = frame[pk_src].astype(str).str.strip()
    frame = frame.loc[
        frame[pk_src].notna()
        & pk_series.ne("")
        & pk_series.str.lower().ne("nan")
        & pk_series.str.lower().ne("none")
    ].copy()
    if frame.empty:
        return empty
    frame[pk_src] = frame[pk_src].astype(str).str.strip()
    frame = frame.drop_duplicates(subset=[pk_src], keep="last")

    # 中文表头保留为合法 PG 标识符，并消除规范化后的重名
    src_cols = [str(col) for col in frame.columns]
    sql_cols = unique_idents(src_cols)
    rename = dict(zip(src_cols, sql_cols, strict=True))
    pk = rename[pk_src]
    frame = frame.rename(columns=rename)
    columns = sql_cols

    from app.core import db as stores

    table = table_name(prefix, project_id)
    engine = stores.raw_engine
    ensure_table(engine, table, columns, pk)
    relax_legacy_primary_key(engine, table, pk)
    dropped = drop_stale_columns(engine, table, columns)
    if dropped:
        logger.info("synced %s schema, dropped %s stale columns", table, len(dropped))
    if align_column_order(engine, table, columns, pk):
        logger.info("aligned %s column order to CSV", table)
    ensure_conflict_target(engine, table, pk)
    purged = purge_empty_pk_rows(engine, table, pk)
    if purged:
        logger.info("removed %s empty-key rows from %s", purged, table)
    rows = _frame_to_value_rows(frame, columns)
    try:
        write = _execute_batches(engine, table, columns, pk, rows)
    except Exception as exc:
        msg = str(exc)
        if "DuplicateColumn" in msg or "specified more than once" in msg:
            raise RuntimeError(
                "入库失败：列名冲突（CSV 表头规范化后出现重复列）。请重试或检查表头。"
            ) from exc
        if "NotNullViolation" in msg or "null value in column" in msg:
            raise RuntimeError(
                "入库失败：表中仍有旧的非空主键列。请重试一次；若仍失败，检查 raw 表结构。"
            ) from exc
        conflictish = (
            "UniqueViolation" in msg
            or "duplicate key value" in msg.lower()
            or "there is no unique or exclusion constraint" in msg.lower()
        )
        if conflictish:
            drop_competing_unique_indexes(engine, table, pk)
            ensure_conflict_target(engine, table, pk)
            try:
                write = _execute_batches(engine, table, columns, pk, rows)
            except Exception as retry_exc:
                raise RuntimeError(
                    f"入库失败：唯一键 {pk} 冲突。"
                    f"请确认 CSV 含该列，且无与其它唯一约束冲突的数据。"
                ) from retry_exc
        else:
            raise
    return {
        "total": int(write.get("rows") or len(rows)),
        "unique": int(frame[pk].nunique()),
        "rows_inserted": int(write.get("rows_inserted") or 0),
        "rows_updated": int(write.get("rows_updated") or 0),
        "table": table,
        "unique_key": pk,
        "dropped_columns": dropped,
    }
