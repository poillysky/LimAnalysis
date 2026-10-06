"""SQL 源表时间窗改写。

模型 SQL 形如 `SELECT ... FROM <source_table> ...`，聚合/清洗需要把它包一层
`WHERE <time_field> >= <window>` 以便走增量。但源表子句是靠字符串定位的
（`rfind(f"FROM {src}")`），一旦 SQL 模板改格式（换行、多子查询、显式 JOIN），
定位就会失败。

旧实现在定位失败时 `return sql` —— 增量**静默退化成全表扫描**，不报错不告警，
数据量上来后才暴露。这里把「是否改写成功」变成显式信号：默认告警并记录，
调用方可选择直接抛错终止本次任务，避免跑一场全量还不知道。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class SourceRewriteError(RuntimeError):
    """源表子句定位失败，SQL 未被加上时间窗限制。"""


def _find_source_clause(sql: str, quoted_source: str) -> tuple[int, str]:
    """定位引用源表的那一处子句，返回 (位置, 关键字)。

    除了 `FROM <src>`，也要认 `JOIN <src>`：模型 SQL 写成
    `FROM 别的表 JOIN <src> ON ...` 时，只找 FROM 会定位失败，
    于是增量静默退化成全量（旧实现就有这个漏）。
    """
    best = (-1, "")
    for keyword in ("FROM", "JOIN"):
        needle = f"{keyword} {quoted_source}"
        idx = sql.rfind(needle)
        if idx > best[0]:
            best = (idx, needle)
    return best


def wrap_source_time_window(
    sql: str,
    source_table: str,
    time_field: str,
    predicate: str,
    *,
    quoted_source: str,
    quoted_column: str,
    context: str = "",
    strict: bool = False,
) -> str:
    """把引用 `<src>` 的子句换成 `(SELECT * FROM <src> WHERE <pred>) AS <src>`。

    :param sql: 原始模型 SQL。
    :param source_table: 源表名（未加引号）。
    :param time_field: 时间字段名（未加引号）。
    :param predicate: 完整 WHERE 条件 SQL 片段（可含绑定参数）。
    :param quoted_source: 已加引号的源表名。
    :param quoted_column: 已加引号的时间字段名。
    :param context: 出现在告警/异常里的场景描述。
    :param strict: True 时定位失败直接抛错；False 时告警并原样返回。
    :return: 改写后的 SQL；定位失败时原样返回。
    """
    idx, needle = _find_source_clause(sql, quoted_source)
    if idx < 0:
        msg = (
            f"未能定位源表 {quoted_source} 的引用子句"
            f"{'（' + context + '）' if context else ''}，"
            f"本次将执行**全量**扫描而不是增量。"
            f"请检查模型 SQL 是否改过格式（换行 / 显式 JOIN / 多层子查询 / 大小写）。"
        )
        if strict:
            raise SourceRewriteError(msg)
        logger.warning(msg)
        return sql

    keyword = needle.split(" ", 1)[0]
    tail = sql[idx + len(needle) :]
    # 别名要搬家：`FROM "t" r ON ...` → `FROM (SELECT * FROM "t" WHERE ...) AS "t" r ON ...`
    # 所以从 tail 里摘掉别名，再拼到新包装后面。
    alias, rest = _leading_alias(tail)
    wrap = (
        f"{keyword} (SELECT * FROM {quoted_source} WHERE {predicate}) "
        f"AS {quoted_source}{alias}"
    )
    logger.debug("已加增量时间窗: %s", context or needle)
    return sql[:idx] + wrap + rest


_ALIAS_STOP = {"WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "LEFT", "RIGHT",
               "INNER", "OUTER", "CROSS", "ON", "UNION", "HAVING", ";"}


def _leading_alias(tail: str) -> tuple[str, str]:
    """取出 `FROM "t" r ON ...` 里紧跟表名的别名。

    返回 (alias_with_leading_space, remaining_tail)；
    没有别名时 alias 为空串，remaining 就是原 tail（保留原有空白）。
    """
    stripped = tail.lstrip()
    if not stripped:
        return "", tail
    token = ""
    for ch in stripped:
        if ch.isalnum() or ch == "_":
            token += ch
        else:
            break
    if not token or token.upper() in _ALIAS_STOP:
        return "", tail
    # 别名与表名之间只允许空白
    if stripped[len(token) : len(token) + 1].strip():
        return "", tail
    return " " + token, tail[len(tail) - len(stripped) + len(token) :]


# 兼容旧的正则化定位：把表名/字段名安全加引号的薄封装
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_ident(name: str) -> str:
    """只允许简单标识符，挡住引号注入。"""
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"非法标识符: {name!r}")
    return f'"{name}"'
