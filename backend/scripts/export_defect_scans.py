"""按「项目 + 次品相 + 时间范围」导出次品扫描表（defect_scans）为 CSV。

用法（工作目录 = backend）：

    .venv/Scripts/python.exe scripts/export_defect_scans.py
    .venv/Scripts/python.exe scripts/export_defect_scans.py --project eagle_rcvr
    .venv/Scripts/python.exe scripts/export_defect_scans.py \
        --project eagle_rcvr --defect-item 烟囱溢胶 \
        --from "2026-07-02 00:00:00" --to "2026-07-04 00:00:00"

默认导出全部项目 / 全部次品相 / 全部时间，且**按次品相分组各出一个文件**
（Excel 里一个次品相一张表，比混在一起好用）。

与页面「数据浏览 → 下载」的差别：

* 页面只支持 ServerTime 起止（且两端必填），本脚本额外支持项目 / 次品相筛选；
* 未指定时间范围时，ServerTime 为空的行**也会导出**（页面按时间筛会把它们丢掉）。

注意 `matched` 列沿用页面口径，输出 Python 的 True / False 字面量；
时间列输出带时区偏移的 ISO 串（如 2026-07-03 10:46:16+08:00）。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.core.db import defect_engine
from app.core.sql_ident import q

TZ = ZoneInfo("Asia/Shanghai")
# 与「数据浏览」页面保持一致的列顺序
COLUMNS = [
    "id",
    "op_id",
    "project_id",
    "project_name",
    "defect_item",
    "sn",
    "machine",
    "cavity",
    "body",
    "matched",
    "created_at",
    "ServerTime",
]
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def parse_dt(value: str | None) -> datetime | None:
    """解析 ISO 时间；不带时区时按 Asia/Shanghai 处理。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw[:-1] if raw.endswith("Z") else raw
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"无法解析时间：{value}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def safe_name(value: str, fallback: str) -> str:
    cleaned = _ILLEGAL.sub("_", str(value or "").strip()).strip(" .")
    return cleaned or fallback


def build_where(args) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if args.project:
        clauses.append("project_id = :project")
        params["project"] = args.project
    if args.defect_item:
        clauses.append("defect_item = :defect_item")
        params["defect_item"] = args.defect_item
    if args.time_from is not None:
        clauses.append('"ServerTime" >= :time_from')
        params["time_from"] = args.time_from
    if args.time_to is not None:
        clauses.append('"ServerTime" <= :time_to')
        params["time_to"] = args.time_to
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, memoryview)):
        return f"<binary {len(value)} bytes>"
    return str(value)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="按项目 / 次品相 / 时间范围导出 defect_scans"
    )
    parser.add_argument("--project", default="", help="项目 ID，缺省=全部项目")
    parser.add_argument("--defect-item", default="", help="次品相，缺省=全部次品相")
    parser.add_argument(
        "--from", dest="time_from", default="", help="ServerTime 起（含）"
    )
    parser.add_argument("--to", dest="time_to", default="", help="ServerTime 止（含）")
    parser.add_argument(
        "--out",
        default=str(repo_root / "exports" / "defect_scans"),
        help="输出目录",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="所有次品相合并为一个文件（默认按次品相拆分为多个文件）",
    )
    args = parser.parse_args()

    args.time_from = parse_dt(args.time_from)
    args.time_to = parse_dt(args.time_to)
    if (
        args.time_from is not None
        and args.time_to is not None
        and args.time_from > args.time_to
    ):
        raise SystemExit("开始时间不能晚于结束时间")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    where, params = build_where(args)
    order = 'ORDER BY project_id, defect_item, "ServerTime" DESC NULLS LAST, id DESC'
    # ServerTime 是建表时加引号的混合大小写列，必须带引号才能引用
    select_cols = ", ".join(f"{q(col)} AS {q(col)}" for col in COLUMNS)
    sql = f"SELECT {select_cols} FROM defect_scans{where} {order}"

    with defect_engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        total_all = conn.execute(
            text("SELECT COUNT(*) FROM defect_scans")
        ).scalar()

    # 按 (项目, 次品相) 分组
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        groups[(str(row["project_id"]), str(row["defect_item"]))].append(row)

    def time_tag() -> str:
        parts = []
        for dt in (args.time_from, args.time_to):
            parts.append(dt.strftime("%Y%m%d%H%M%S") if dt else "all")
        return "_".join(parts)

    written: list[tuple[Path, int]] = []
    buckets = (
        [(("", ""), rows)] if args.merge or not rows else sorted(groups.items())
    )
    for (project, item), items in buckets:
        if args.merge:
            name = safe_name(args.project, "all") + "_all-items"
        elif args.defect_item and not args.project:
            name = f"{safe_name(item, 'item')}"
        else:
            name = (
                f"{safe_name(project, 'project')}_{safe_name(item, 'item')}"
            )
        # 无筛选用 merge 时 name 可能是空串拼接
        name = safe_name(name, "defect_scans")
        path = out_dir / f"{name}_{time_tag()}.csv"

        # utf-8-sig：带 BOM，Excel 直接双击不乱码（与页面下载一致）
        with path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(COLUMNS)
            for row in items:
                writer.writerow([cell(row[col]) for col in COLUMNS])
        written.append((path, len(items)))

    print(f"库内 defect_scans 总行数：{total_all}")
    print(f"本次筛选命中行数：{len(rows)}")
    print(f"筛选条件：project={args.project or '(全部)'} "
          f"defect_item={args.defect_item or '(全部)'} "
          f"from={args.time_from or '(不限制)'} to={args.time_to or '(不限制)'}")
    if args.time_from is None and args.time_to is None:
        print("时间范围未限制：ServerTime 为空的行已一并导出")
    print(f"输出目录：{out_dir}")
    for path, count in written:
        print(f"  {path.name}  ({count} 行)")


if __name__ == "__main__":
    main()
