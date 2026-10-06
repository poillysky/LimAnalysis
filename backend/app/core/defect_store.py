"""次品库：Postgres lim_defect。SN 事实在写入时从 lim_raw 补全机台/模穴/本体。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    bindparam,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core import db as stores
from app.core.projects import load_system_defaults
from app.core.sql_ident import ident, q, table_name

TZ = ZoneInfo("Asia/Shanghai")


class DefectBase(DeclarativeBase):
    pass


class DefectUploadOp(DefectBase):
    __tablename__ = "defect_upload_ops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    defect_item: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class DefectScanRow(DefectBase):
    __tablename__ = "defect_scans"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "sn",
            "defect_item",
            name="uq_defect_scans_project_sn_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    defect_item: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sn: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    machine: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    cavity: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    body: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


def ensure_defect_tables() -> None:
    DefectBase.metadata.create_all(stores.defect_engine)


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        stamp = value.astimezone(TZ) if value.tzinfo else value.replace(tzinfo=TZ)
        return stamp.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")


def op_to_dict(row: DefectUploadOp) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "project_name": row.project_name,
        "defect_item": row.defect_item,
        "method": row.method,
        "method_label": "文件上传" if row.method == "file" else "扫码上传",
        "count": row.count,
        "created_at": _fmt_time(row.created_at),
    }


def _pick_col(columns: list[str], *names: str) -> str | None:
    exact = {name: name for name in columns}
    lower = {name.lower(): name for name in columns}
    for name in names:
        if name in exact:
            return exact[name]
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def _body_from_sn(sn: str) -> str:
    code = str(sn or "").strip()
    if len(code) >= 14:
        return code[12:14]
    return ""


def lookup_raw_profiles(project: dict, sns: list[str]) -> dict[str, dict]:
    """按项目 raw 表唯一键批量取机台/模穴/本体。"""
    table = table_name(str(project.get("prefix") or ""), str(project.get("project_id") or ""))
    inspector = inspect(stores.raw_engine)
    table_i = ident(table)
    if inspector.has_table(table_i):
        table = table_i
    elif not inspector.has_table(table):
        return {}
    columns = [str(col["name"]) for col in inspector.get_columns(table)]
    defaults = load_system_defaults()
    pk_name = str((defaults.get("unique_key") or {}).get("column") or "FCoverSN").strip()
    sn_col = _pick_col(columns, pk_name, "FCoverSN", "前盖码", "SN", "sn")
    if not sn_col:
        return {}
    machine_col = _pick_col(columns, "机台")
    cavity_col = _pick_col(columns, "模穴", "模具模穴")
    body_col = _pick_col(columns, "本体")
    select_cols = [q(ident(sn_col))]
    if machine_col:
        select_cols.append(q(ident(machine_col)))
    if cavity_col:
        select_cols.append(q(ident(cavity_col)))
    if body_col:
        select_cols.append(q(ident(body_col)))
    sql = text(
        f"SELECT {', '.join(select_cols)} FROM {q(ident(table))} "
        f"WHERE BTRIM(({q(ident(sn_col))})::text) IN :sns"
    ).bindparams(bindparam("sns", expanding=True))
    out: dict[str, dict] = {}
    with stores.raw_engine.connect() as conn:
        rows = conn.execute(sql, {"sns": sns}).mappings().all()
    for row in rows:
        sn = str(row.get(sn_col) or "").strip()
        if not sn:
            continue
        machine = str(row.get(machine_col) or "").strip() if machine_col else ""
        cavity = str(row.get(cavity_col) or "").strip() if cavity_col else ""
        body = str(row.get(body_col) or "").strip() if body_col else ""
        if not body:
            body = _body_from_sn(sn)
        out[sn] = {
            "machine": machine,
            "cavity": cavity,
            "body": body,
            "matched": True,
        }
    return out


def insert_upload(
    *,
    project: dict,
    defect_item: str,
    method: str,
    sns: list[str],
) -> dict:
    ensure_defect_tables()
    codes = list(sns)
    now = datetime.now(TZ)
    pid = str(project.get("project_id") or "").strip()
    name = str(project.get("display_name") or pid)
    how = "file" if method == "file" else "scan"
    profiles = lookup_raw_profiles(project, codes)
    db = stores.DefectSession()
    try:
        op = DefectUploadOp(
            project_id=pid,
            project_name=name,
            defect_item=defect_item,
            method=how,
            count=len(codes),
            created_at=now,
        )
        db.add(op)
        db.flush()
        payload = []
        for code in codes:
            info = profiles.get(code) or {}
            payload.append(
                {
                    "op_id": op.id,
                    "project_id": pid,
                    "project_name": name,
                    "defect_item": defect_item,
                    "sn": code,
                    "machine": str(info.get("machine") or ""),
                    "cavity": str(info.get("cavity") or ""),
                    "body": str(info.get("body") or _body_from_sn(code)),
                    "matched": bool(info.get("matched")),
                    "created_at": now,
                }
            )
        stmt = pg_insert(DefectScanRow).values(payload)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_defect_scans_project_sn_item",
            set_={
                "op_id": stmt.excluded.op_id,
                "project_name": stmt.excluded.project_name,
                "machine": stmt.excluded.machine,
                "cavity": stmt.excluded.cavity,
                "body": stmt.excluded.body,
                "matched": stmt.excluded.matched,
                "created_at": stmt.excluded.created_at,
            },
        )
        db.execute(stmt)
        db.commit()
        db.refresh(op)
        return {"count": op.count, "op": op_to_dict(op)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_ops(
    *,
    project_id: str | None = None,
    defect_item: str | None = None,
    limit: int = 200,
) -> dict:
    ensure_defect_tables()
    db = stores.DefectSession()
    try:
        stmt = select(DefectUploadOp).order_by(DefectUploadOp.id.desc())
        pid = str(project_id or "").strip()
        if pid:
            stmt = stmt.where(DefectUploadOp.project_id == pid)
        item = str(defect_item or "").strip()
        if item:
            stmt = stmt.where(DefectUploadOp.defect_item == item)
        cap = max(1, min(500, int(limit or 200)))
        rows = db.scalars(stmt.limit(cap)).all()
        return {"ops": [op_to_dict(row) for row in rows]}
    finally:
        db.close()


def _window_hours(hours: int | None) -> int:
    try:
        value = int(hours if hours is not None else 12)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(72, value))


def _stamp_label(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        stamp = value.astimezone(TZ) if value.tzinfo else value.replace(tzinfo=TZ)
        return stamp.strftime("%m-%d %H:%M")
    return str(value)[:16]


def _rate(qty: int, ng: int) -> tuple[float | None, float | None]:
    if qty <= 0:
        return None, None
    rate = ng / qty
    return rate, round(rate * 100, 2)


def _raw_layout(project: dict) -> dict | None:
    table = table_name(str(project.get("prefix") or ""), str(project.get("project_id") or ""))
    inspector = inspect(stores.raw_engine)
    table_i = ident(table)
    if inspector.has_table(table_i):
        table = table_i
    elif not inspector.has_table(table):
        return None
    columns = [str(col["name"]) for col in inspector.get_columns(table)]
    defaults = load_system_defaults()
    pk_name = str((defaults.get("unique_key") or {}).get("column") or "FCoverSN").strip()
    sn_col = _pick_col(columns, pk_name, "FCoverSN", "前盖码", "SN", "sn")
    time_col = _pick_col(columns, "ServerTime", "ingested_at", "检测时间", "时间")
    if not sn_col or not time_col:
        return None
    return {
        "table": table,
        "sn": sn_col,
        "time": time_col,
        "machine": _pick_col(columns, "机台"),
        "cavity": _pick_col(columns, "模穴", "模具模穴"),
        "body": _pick_col(columns, "本体"),
    }


def _list_defect_sns(project_id: str, defect_item: str | None) -> list[str]:
    ensure_defect_tables()
    db = stores.DefectSession()
    try:
        stmt = select(DefectScanRow.sn).where(DefectScanRow.project_id == project_id)
        item = str(defect_item or "").strip()
        if item:
            stmt = stmt.where(DefectScanRow.defect_item == item)
        rows = db.scalars(stmt).all()
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            code = str(row or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
        return out
    finally:
        db.close()


def _group_rows(sql, params: dict) -> list[dict]:
    with stores.raw_engine.connect() as conn:
        stmt = text(sql)
        if isinstance(params.get("sns"), (list, tuple)):
            stmt = stmt.bindparams(bindparam("sns", expanding=True))
        records = conn.execute(stmt, params).mappings().all()
    return [dict(row) for row in records]


def _merge_qty_ng(qty_rows: list[dict], ng_rows: list[dict], left: str, right: str) -> list[dict]:
    ng_map = {
        (str(row.get(left) or "").strip(), str(row.get(right) or "").strip()): int(
            row.get("ng") or 0
        )
        for row in ng_rows
    }
    out = []
    for row in qty_rows:
        a = str(row.get(left) or "").strip()
        b = str(row.get(right) or "").strip()
        if not a:
            continue
        qty = int(row.get("qty") or 0)
        ng = int(ng_map.get((a, b), 0))
        rate, pct = _rate(qty, ng)
        item = {left: a, right: b, "qty": qty, "ng": ng, "rate": rate, "rate_pct": pct}
        out.append(item)
    return out


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


def _parse_pairs(values) -> list[tuple[str, str]]:
    raws: list[str] = []
    if values is None:
        return []
    if isinstance(values, str):
        raws = values.replace(";", ",").split(",")
    elif isinstance(values, (list, tuple)):
        for item in values:
            raws.extend(str(item or "").replace(";", ",").split(","))
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raws:
        text_val = str(raw or "").strip()
        if ":" not in text_val:
            continue
        left, right = text_val.split(":", 1)
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


def _exclude_machine_cavity_sql(layout: dict, pairs) -> tuple[str, dict]:
    """从本体表去掉 LIM 异常格：机台 × 模穴末位字母对应的原始行不进汇总。"""
    if not layout.get("machine") or not layout.get("cavity"):
        return "", {}
    items = _parse_pairs(pairs)
    if not items:
        return "", {}
    machine_sql = f"BTRIM(({q(ident(layout['machine']))})::text)"
    cavity_sql = f"BTRIM(({q(ident(layout['cavity']))})::text)"
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


def _exclude_body_cavity_sql(body_expr: str, pairs) -> tuple[str, dict]:
    """从机台表去掉本体异常格：模具 × 穴位（1–8 / A–H）对应的原始行不进汇总。"""
    items = _parse_pairs(pairs)
    if not items:
        return "", {}
    mold_sql = f"SUBSTRING({body_expr} FROM 1 FOR 1)"
    digit_sql = f"SUBSTRING({body_expr} FROM 2 FOR 1)"
    clauses: list[str] = []
    params: dict = {}
    for i, (mold, cavity) in enumerate(items):
        digit = _BODY_LETTER_TO_DIGIT.get(cavity, cavity)
        if not mold.isdigit() or digit not in "12345678":
            continue
        mkey, dkey = f"xbc_m_{i}", f"xbc_d_{i}"
        clauses.append(f"({mold_sql} = :{mkey} AND {digit_sql} = :{dkey})")
        params[mkey] = mold
        params[dkey] = digit
    if not clauses:
        return "", {}
    return f" AND NOT ({' OR '.join(clauses)})", params


def query_analysis(
    project_id: str,
    *,
    hours: int = 12,
    defect_item: str | None = None,
    exclude_machine_cavities=None,
    exclude_body_cavities=None,
) -> dict:
    """窗口内原始库产量 × 次品库 SN：LIM 机台×模穴、本体×模穴。"""
    from app.core.projects import get_project

    pid = str(project_id or "").strip()
    project = get_project(pid)
    if project is None:
        raise ValueError("项目不存在")
    window = _window_hours(hours)
    layout = _raw_layout(project)
    empty = {
        "project_id": pid,
        "hours": window,
        "from_hour": "",
        "to_hour": "",
        "defect_item": str(defect_item or "").strip(),
        "machines": [],
        "bodies": [],
    }
    if not layout:
        return empty
    table_sql = q(ident(layout["table"]))
    time_sql = f"NULLIF(BTRIM(({q(ident(layout['time']))})::text), '')::timestamptz"
    sn_sql = q(ident(layout["sn"]))
    catalog = [
        str(item).strip()
        for item in (project.get("machines") or [])
        if str(item).strip()
    ]
    bounds_sql = (
        f"WITH bounds AS (SELECT MAX({time_sql}) AS hi FROM {table_sql}) "
    )
    time_filter = (
        f" FROM {table_sql}, bounds "
        f"WHERE bounds.hi IS NOT NULL "
        f"AND {time_sql} >= bounds.hi - (:hours) * INTERVAL '1 hour' "
        f"AND NULLIF(BTRIM(({sn_sql})::text), '') IS NOT NULL"
    )
    base_params: dict = {"hours": window}
    lohi_sql = (
        f"{bounds_sql}SELECT MIN({time_sql}) AS lo, MAX({time_sql}) AS hi "
        f"{time_filter}"
    )
    lohi_rows = _group_rows(lohi_sql, base_params)
    lohi = lohi_rows[0] if lohi_rows else {}
    sns = _list_defect_sns(pid, defect_item)
    machines: list[dict] = []
    bodies: list[dict] = []
    if layout.get("body"):
        body_expr = (
            f"COALESCE(NULLIF(BTRIM(({q(ident(layout['body']))})::text), ''), "
            f"SUBSTRING(BTRIM(({sn_sql})::text) FROM 13 FOR 2))"
        )
    else:
        body_expr = f"SUBSTRING(BTRIM(({sn_sql})::text) FROM 13 FOR 2)"
    machine_excl, machine_ex_params = _exclude_machine_cavity_sql(
        layout, exclude_machine_cavities
    )
    body_excl, body_ex_params = _exclude_body_cavity_sql(
        body_expr, exclude_body_cavities
    )
    if layout.get("machine") and layout.get("cavity"):
        machine_sql = q(ident(layout["machine"]))
        cavity_sql = q(ident(layout["cavity"]))
        machine_filter = (
            f"{time_filter} AND BTRIM(({machine_sql})::text) <> ''{body_excl}"
        )
        machine_params = dict(base_params)
        machine_params.update(body_ex_params)
        qty_sql = (
            f"{bounds_sql}SELECT BTRIM(({machine_sql})::text) AS machine, "
            f"BTRIM(({cavity_sql})::text) AS cavity, "
            f"COUNT(DISTINCT BTRIM(({sn_sql})::text))::int AS qty "
            f"{machine_filter} GROUP BY 1, 2"
        )
        qty_rows = _group_rows(qty_sql, dict(machine_params))
        ng_rows: list[dict] = []
        if sns:
            ng_sql = (
                f"{bounds_sql}SELECT BTRIM(({machine_sql})::text) AS machine, "
                f"BTRIM(({cavity_sql})::text) AS cavity, "
                f"COUNT(DISTINCT BTRIM(({sn_sql})::text))::int AS ng "
                f"{machine_filter} AND BTRIM(({sn_sql})::text) IN :sns "
                f"GROUP BY 1, 2"
            )
            ng_params = dict(machine_params)
            ng_params["sns"] = sns
            ng_rows = _group_rows(ng_sql, ng_params)
        machines = _merge_qty_ng(qty_rows, ng_rows, "machine", "cavity")
        if catalog:
            allowed = set(catalog)
            machines = [row for row in machines if row["machine"] in allowed]
    mold_sql = f"SUBSTRING({body_expr} FROM 1 FOR 1)"
    hole_sql = f"SUBSTRING({body_expr} FROM 2 FOR 1)"
    body_filter = (
        f"{time_filter} AND CHAR_LENGTH({body_expr}) >= 2 "
        f"AND {mold_sql} ~ '^[0-9]$' AND {hole_sql} ~ '^[1-8]$'"
        f"{machine_excl}"
    )
    body_params = dict(base_params)
    body_params.update(machine_ex_params)
    qty_sql = (
        f"{bounds_sql}SELECT {mold_sql} AS body, {hole_sql} AS cavity, "
        f"COUNT(DISTINCT BTRIM(({sn_sql})::text))::int AS qty "
        f"{body_filter} GROUP BY 1, 2"
    )
    qty_rows = _group_rows(qty_sql, dict(body_params))
    ng_rows = []
    if sns:
        ng_sql = (
            f"{bounds_sql}SELECT {mold_sql} AS body, {hole_sql} AS cavity, "
            f"COUNT(DISTINCT BTRIM(({sn_sql})::text))::int AS ng "
            f"{body_filter} AND BTRIM(({sn_sql})::text) IN :sns "
            f"GROUP BY 1, 2"
        )
        ng_params = dict(body_params)
        ng_params["sns"] = sns
        ng_rows = _group_rows(ng_sql, ng_params)
    bodies = _merge_qty_ng(qty_rows, ng_rows, "body", "cavity")
    return {
        "project_id": pid,
        "hours": window,
        "from_hour": _stamp_label(lohi.get("lo")),
        "to_hour": _stamp_label(lohi.get("hi")),
        "defect_item": str(defect_item or "").strip(),
        "machines": machines,
        "bodies": bodies,
    }
