"""SQL 标识符与表达式安全校验 —— 全项目零依赖的底层工具。

## 为什么单独成模块（不要合回去）

这5 个函数原先寄居在别处，位置本身制造了架构倒挂：

- ``ident`` / ``unique_idents`` / ``q`` / ``table_name`` 原在``collector/raw_loader.py``
  → 于是 ``app/core/ads_query.py`` 与 ``app/core/defect_store.py`` 只能在**模块顶层**
  反向 ``import collector``。``app.core`` 是最底层，却依赖了最上层的采集包。
- ``is_safe_sql_expression`` 原在 ``processor/validators.py``
  → 于是 ``app/core/ai_client.py`` 得在函数体内延迟 import processor 才能做一次关键字校验。

一个纯 ``re`` 工具（30 行）住在业务包里，让三个包互相反向依赖。搬到这里后
``app.core`` 对上层的依赖归零，依赖方向恢复单向：

    app.core  ←  collector  ←  processor
       ↑
   FastAPI 路由层（延迟导入业务包，方向本来就对）

**规则：本模块只能 ``import re``。** 任何要import app / collector / processor / sqlalchemy
的需求都说明那个函数放错了地方，别往这里塞。
"""

from __future__ import annotations

import re

__all__ = [
    "ident",
    "unique_idents",
    "q",
    "table_name",
    "is_safe_sql_expression",
]


def ident(name: str) -> str:
    """SQL 标识符：保留中文等 Unicode 字母，避免「模穴/结果」全被洗成重复的 col。"""
    cleaned = re.sub(r"[^\w]+", "_", str(name), flags=re.UNICODE).strip("_")
    cleaned = cleaned.replace('"', "")
    if not cleaned:
        cleaned = "col"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:60]


def unique_idents(columns: list[str]) -> list[str]:
    """将列名映射为互不重复的 SQL 标识符（保持顺序）。"""
    used: dict[str, int] = {}
    result: list[str] = []
    for col in columns:
        base = ident(col)
        key = base.lower()
        n = used.get(key, 0)
        used[key] = n + 1
        if n == 0:
            result.append(base)
            continue
        suffix = f"_{n + 1}"
        result.append((base[: 60 - len(suffix)] + suffix))
    return result


def q(name: str) -> str:
    """name 已是（或将经 ident）安全标识符；对已规范化名不再二次变形冲突。"""
    safe = name if re.fullmatch(r"[\w]+", str(name), flags=re.UNICODE) else ident(name)
    safe = str(safe).replace('"', "")
    return f'"{safe}"'


def table_name(prefix: str, project_id: str) -> str:
    base = ident(prefix or project_id)
    return f"{base}_raw"


# SQL 表达式安全校验：黑名单关键字 + 语句分隔符 + 注释符。
# 只做「明显危险」拦截，不试图当解析器使；AI 生成的公式走这条路径。
_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|INSERT|UPDATE|ALTER|CREATE|GRANT|REVOKE|COPY|"
    r"EXECUTE|CALL|MERGE)\b",
    re.IGNORECASE,
)


def is_safe_sql_expression(formula: str) -> bool:
    text = str(formula or "").strip()
    if not text:
        return False
    if _FORBIDDEN.search(text):
        return False
    if ";" in text:
        return False
    if "--" in text or "/*" in text:
        return False
    return True