"""磁盘目录浏览：枚举盘符 / 列出子目录。

从 app/core/inspection.py 拆出（该簇内聚、只被门面调用）。
"""

from __future__ import annotations

import os
from pathlib import Path

SKIP_DIR_NAMES = frozenset(
    {
        "$recycle.bin",
        "boot",
        "config.msi",
        "documents and settings",
        "msocache",
        "program files",
        "program files (x86)",
        "programdata",
        "recovery",
        "system volume information",
        "windows",
    }
)


def _drive_roots() -> list[Path]:
    if os.name != "nt":
        return [Path("/")]
    roots: list[Path] = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = Path(f"{letter}:/")
        try:
            if path.exists():
                roots.append(path)
        except OSError:
            continue
    return roots


def _resolve_dir(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        from app.core.config import settings as app_settings

        path = app_settings.REPO_ROOT / path
    return path.resolve()


def _dir_label(path: Path) -> str:
    if os.name == "nt" and len(path.parts) <= 1:
        text = str(path)
        return text if text.endswith("\\") else f"{text}\\"
    return path.name or str(path)


def _is_listed_dir(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name.lower() in SKIP_DIR_NAMES:
        return False
    try:
        return path.is_dir()
    except OSError:
        return False


def list_dir_entries(parent: str | None = None) -> dict:
    raw = str(parent or "").strip()
    if not raw:
        dirs = [
            {"path": str(item), "name": _dir_label(item)} for item in _drive_roots()
        ]
        return {"parent": "", "up": "", "dirs": dirs}

    path = _resolve_dir(raw)
    if not path.is_dir():
        raise ValueError(f"目录不存在：{path}")
    try:
        children = sorted(
            (item for item in path.iterdir() if _is_listed_dir(item)),
            key=lambda item: item.name.lower(),
        )
    except OSError as exc:
        raise ValueError(f"无法列出目录：{path}") from exc
    parent_dir = path.parent
    up = "" if parent_dir == path else str(parent_dir)
    return {
        "parent": str(path),
        "up": up,
        "dirs": [{"path": str(item), "name": _dir_label(item)} for item in children],
    }
