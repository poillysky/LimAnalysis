"""文件名解析：从照片文件名提取穴位字母与检测状态。

从 app/core/inspection.py 拆出。纯函数，仅依赖标准库 re / pathlib。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.inspection_parts.constants import CAVITY_LETTERS, VIEWER_STATUSES


def extract_cavity(filename: str) -> str:
    """从文件名解析穴位字母（兼容逗号尾缀 / 下划线分段 / 路径片段）。"""
    stem = Path(filename).stem
    tail = stem.rsplit(",", 1)[-1].strip().upper()
    if tail in CAVITY_LETTERS:
        return tail
    for part in re.split(r"[,_\-\s/\\]+", stem):
        token = part.strip().upper()
        if token in CAVITY_LETTERS:
            return token
    matched = re.search(
        r"(?:^|[,_\-\s])([A-HJ-NP-QR])(?:$|[,_\-\s])",
        stem,
        flags=re.IGNORECASE,
    )
    if matched:
        letter = matched.group(1).upper()
        if letter in CAVITY_LETTERS:
            return letter
    return ""


def extract_status(filename: str) -> str:
    """从文件名识别是否命中已知查看状态枚举。"""
    stem = Path(filename).stem
    head = stem.split(",", 1)[0].strip()
    if head in VIEWER_STATUSES:
        return head
    for status in VIEWER_STATUSES:
        if status and status in stem:
            return status
    return ""
