"""差分验证：sql_ident.py 的 5 个函数与改前快照逐用例比对。

从改前快照（collector/raw_loader.py + processor/validators.py）里 exec 出旧实现，
与新模块逐用例比对返回值。任何不一致直接 fail。

跑法：cd backend && .venv/Scripts/python.exe scripts/_diff_sql_ident.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

SNAP = Path(os.environ.get("LIM_SNAP_DIR", "")) if os.environ.get("LIM_SNAP_DIR") else None
if SNAP is None:
    raise SystemExit("需要环境变量 LIM_SNAP_DIR 指向改前快照目录")


def load_old() -> dict:
    """从快照 exec 出旧实现。只取需要的顶层定义，避开 pandas 等重依赖。"""
    raw_src = (SNAP / "collector_raw_loader.py" / "raw_loader.py").read_text(encoding="utf-8")
    val_src = (SNAP / "processor_validators.py" / "validators.py").read_text(encoding="utf-8")

    def grab(src: str, names: list[str]) -> str:
        """按 `def name(` 定位，切到下一个顶层 def/class 为止。"""
        out = []
        for name in names:
            m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
            if not m:
                raise SystemExit(f"快照里找不到 {name}")
            start = m.start()
            nxt = re.search(r"^(?:def |class |@)", src[m.end():], re.M)
            end = m.end() + nxt.start() if nxt else len(src)
            out.append(src[start:end].rstrip() + "\n")
        return "\n\n".join(out)

    ns: dict = {"re": re}
    # 模块级常量也要带上：is_safe_sql_expression 依赖 _FORBIDDEN。
    # 只抽它自己用到的那一个，避免把整个 validators 的 import 链拖进来。
    consts = re.search(r"^_FORBIDDEN = re\.compile\([\s\S]*?\)\n", val_src, re.M)
    if not consts:
        raise SystemExit("快照里找不到 _FORBIDDEN")
    exec(  # noqa: S102 - 差分测试刻意执行旧实现
        consts.group(0) + "\n\n"
        + grab(raw_src, ["ident", "unique_idents", "q", "table_name"]) + "\n\n"
        + grab(val_src, ["is_safe_sql_expression"]),
        ns,
    )
    return ns


IDENT_CASES = [
    "", " ", "模穴", "结果", "a b", "a-b", "a__b", "__a__", '"quoted"', 'a"b',
    "1abc", "9", "0", "1234567890", "a1", "A1", "a_1", "数量", "数量 ",
 "  数量", "ServerTime", "server_time", "serverTime", "FCoverSN",
    "!!!", "@@@", "###", "a!b@c#d", "-", "_", "___", "a-b-c-d",
    "very_long_column_name_that_exceeds_sixty_characters_limit_for_sure_yes",
    "x" * 59, "x" * 60, "x" * 61, "x" * 100, "x" * 200,
    "表名.with.dots", "with space and 中文", "中文English混合123",
    "NULL", "null", "select", "SELECT * FROM t",
    "with'quote", "with\"dquote", "back`tick", "semi;colon",
    "tab\tname", "new\nline", "emoji😀name",
]
for _i in range(200):
    IDENT_CASES.append("".join(chr(0x4E00 + (_i * 7 + k * 13) % 2000) for k in range(1 + _i % 12)))
    IDENT_CASES.append(f"col{_i}_{'dup' if _i % 2 else 'x'}")
    IDENT_CASES.append(f"{'A' * (_i % 70)}{_i}")

UNIQUE_CASES = [
    [],
    ["a"],
    ["a", "a"],
    ["a", "a", "a"],
    ["A", "a"],
    ["模穴", "模穴"],
    ["模穴", "结果", "模穴"],
    ["a b", "a-b", "a_b"],
    ["1x", "1y"],
    ["", "", ""],
    ["x" * 70, "x" * 70],
    ["x" * 70, "x" * 70, "x" * 70],
    [f"col{i}" for i in range(60)],
]
for _i in range(120):
    UNIQUE_CASES.append([f"n{_i % 5}" for _ in range(_i % 9)])
    UNIQUE_CASES.append([f"dup" for _ in range(_i % 7)])
    UNIQUE_CASES.append(["x" * (55 + _i % 20)] * (1 + _i % 4))

TABLE_CASES = [
    ("proj", "proj"), ("", "proj"), ("", ""), (None, "abc"),
    ("p1", ""), ("", "p1"), ("中文", "x"), ("a b", "c-d"),
    ("x" * 100, "y"), ("", "x" * 100), ("__", "##"), ("9", "8"),
]
for _i in range(60):
    TABLE_CASES.append((f"pfx{_i}" if _i % 2 else "", f"pid{_i}"))

SAFE_CASES = [
    "", "   ", "a", "a+b", "SUM(x)", "sum(x)", "a * b / c",
    "DROP TABLE t", "drop table t", "  DROP  TABLE  t  ",
    "SELECT * FROM t", "select 1", "DELETE FROM t", "TRUNCATE t",
    "INSERT INTO t VALUES (1)", "UPDATE t SET a=1", "ALTER TABLE t ADD c int",
    "CREATE TABLE t()", "GRANT ALL", "REVOKE ALL", "COPY t FROM '/etc/passwd'",
    "EXECUTE f()", "CALL p()", "MERGE INTO t", "a; b", "a;b", "a -- b",
    "a /* b */ c", "a/*b*/", "merged", "updated_at", "created",
    "呼叫机台机台", "modality", "replicated", "droplet",
    "SUM(CASE WHEN a>1 THEN 1 ELSE 0 END)",
    "a" * 500, ";" * 10, "--" * 10,
    "DROP\nTABLE", "drop\ttable", "SELECT * FROM t; --",
]
for _i in range(120):
    SAFE_CASES.append("".join(
        ("DROP", "select", "SUM(a)", ";", "--", "/*", "x", " ")[k % 8]
        for k in range(_i % 9 + 1)
    ))


def main() -> int:
    old = load_old()
    from app.core import sql_ident as new

    checks = 0
    fails: list[str] = []

    def cmp(name: str, argname: str, args, olds, news):
        nonlocal checks
        for a, o, n in zip(args, olds, news):
            checks += 1
            if o != n:
                fails.append(f"{name}({argname}={a!r}): 旧={o!r} 新={n!r}")

    # ident
    o = [old["ident"](c) for c in IDENT_CASES]
    n = [new.ident(c) for c in IDENT_CASES]
    cmp("ident", "name", IDENT_CASES, o, n)

    # unique_idents
    o = [old["unique_idents"](c) for c in UNIQUE_CASES]
    n = [new.unique_idents(c) for c in UNIQUE_CASES]
    cmp("unique_idents", "columns", UNIQUE_CASES, o, n)

    # q
    o = [old["q"](c) for c in IDENT_CASES]
    n = [new.q(c) for c in IDENT_CASES]
    cmp("q", "name", IDENT_CASES, o, n)

    # table_name
    o = [old["table_name"](*c) for c in TABLE_CASES]
    n = [new.table_name(*c) for c in TABLE_CASES]
    cmp("table_name", "args", TABLE_CASES, o, n)

    # is_safe_sql_expression
    o = [old["is_safe_sql_expression"](c) for c in SAFE_CASES]
    n = [new.is_safe_sql_expression(c) for c in SAFE_CASES]
    cmp("is_safe_sql_expression", "formula", SAFE_CASES, o, n)

    print(f"差分用例{checks} 条，失败 {len(fails)} 条")
    for f in fails[:20]:
        print("  FAIL", f)

    # 额外断言：新模块必须零重依赖（防止以后有人往里塞 import）
    src = (BACKEND / "app" / "core" / "sql_ident.py").read_text(encoding="utf-8")
    body = re.sub(r'"""[\s\S]*?"""', "", src, count=1)
    body = re.sub(r"#.*", "", body)
    bad = [
        m.group(0)
        for m in re.finditer(r"^\s*(?:from|import)\s+[\w.]+", body, re.M)
        if not re.match(r"(?:from|import)\s+re$", m.group(0).strip())
        and "__future__" not in m.group(0)
    ]
    if bad:
        print("  FAIL sql_ident.py 出现非 re 依赖:", bad)
        return 1

    if fails:
        return 1
    print("PASS：与改前实现逐用例全等，且新模块零重依赖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())