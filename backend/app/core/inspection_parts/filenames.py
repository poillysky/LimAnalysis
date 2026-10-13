"""文件名解析：从照片文件名提取穴位字母、检测状态与 SN。

从 app/core/inspection.py 拆出。纯函数，仅依赖标准库 re / pathlib。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.inspection_parts.constants import CAVITY_LETTERS, VIEWER_STATUSES


def extract_sn(filename: str) -> str:
    """解析 SN 字母串。

    - 注塑常见：`OK,sample03,A.jpg` → `sample03`（去掉状态头 + 穴位尾）
    - 外观常见：`截图SN001_视角.jpg` → `SN001`（去掉截图前缀与末段视角）
    """
    stem = Path(filename).stem.strip()
    if not stem:
        return ""
    if stem.startswith("截图"):
        stem = stem[2:]
    if "," in stem:
        parts = [p.strip() for p in stem.split(",") if p.strip()]
        if len(parts) >= 2:
            start = 1 if parts[0] in VIEWER_STATUSES else 0
            end = len(parts) - (1 if parts[-1].upper() in CAVITY_LETTERS else 0)
            mid = parts[start:end]
            if mid:
                return mid[0] if len(mid) == 1 else ",".join(mid)
            return ""
    if "_" in stem:
        return stem.rsplit("_", 1)[0].strip()
    return stem.strip()


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
