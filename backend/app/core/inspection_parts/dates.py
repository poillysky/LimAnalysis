"""外观检测目录：日期目录名归一与解析。

从 app/core/inspection.py 拆出。纯函数簇（只依赖 re / pathlib），
便于单独测试与复用。
"""

from __future__ import annotations

import re
from pathlib import Path


def appearance_date_sort_key(name: str) -> str:
    """把 2026.10.07 / 20261007 / 2026-10-07 归一成 YYYYMMDD 便于倒序。"""
    text = str(name or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return text


def appearance_is_date_dir(name: str) -> bool:
    return bool(
        re.fullmatch(r"\d{8}", name)
        or re.fullmatch(r"\d{4}[.\-]\d{2}[.\-]\d{2}", name)
    )


def appearance_date_aliases(date_str: str) -> list[str]:
    raw = str(date_str or "").strip()
    if not raw:
        return []
    aliases = [raw]
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 8:
        ymd = digits[:8]
        dotted = f"{ymd[:4]}.{ymd[4:6]}.{ymd[6:8]}"
        dashed = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
        for item in (ymd, dotted, dashed):
            if item not in aliases:
                aliases.append(item)
    return aliases


def appearance_resolve_date_dir(session_dir: Path, date_str: str) -> Path | None:
    if not session_dir.is_dir():
        return None
    for name in appearance_date_aliases(date_str):
        candidate = session_dir / name
        if candidate.is_dir():
            return candidate
    want = appearance_date_sort_key(date_str)
    if not want:
        return None
    try:
        for item in session_dir.iterdir():
            if item.is_dir() and appearance_date_sort_key(item.name) == want:
                return item
    except OSError:
        return None
    return None
