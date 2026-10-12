"""项目级 CSV 列名映射：入库前把原列名改成统一名。

例：BCoverSN → FCoverSN。配置在项目 config.column_map，采集/上传/同步表结构时生效。
"""

from __future__ import annotations

from typing import Any


def normalize_column_map(raw: Any) -> list[dict[str, str]]:
    """规范化为 [{source, target}, ...]；source=CSV 原名，target=入库名。"""
    items: list[Any]
    if isinstance(raw, dict):
        items = [{"source": k, "target": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    out: list[dict[str, str]] = []
    seen_src: set[str] = set()
    seen_tgt: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(
            item.get("source") or item.get("from") or item.get("原名") or ""
        ).strip()
        target = str(
            item.get("target") or item.get("to") or item.get("指定名") or ""
        ).strip()
        if not source or not target or source == target:
            continue
        src_key = source.lower()
        tgt_key = target.lower()
        if src_key in seen_src or tgt_key in seen_tgt:
            continue
        if len(source) > 100 or len(target) > 100:
            continue
        seen_src.add(src_key)
        seen_tgt.add(tgt_key)
        out.append({"source": source, "target": target})
    return out


def column_map_of(project: dict | None) -> list[dict[str, str]]:
    if not project:
        return []
    return normalize_column_map(project.get("column_map"))


def apply_column_map(frame, project: dict | None = None):
    """按项目映射重命名 DataFrame 列；无映射则原样返回。"""
    mapping = column_map_of(project)
    if not mapping or frame is None:
        return frame
    columns = [str(c) for c in frame.columns]
    lower = {c.lower(): c for c in columns}
    rename: dict[str, str] = {}
    for item in mapping:
        source = item["source"]
        target = item["target"]
        actual = source if source in frame.columns else lower.get(source.lower())
        if not actual:
            continue
        if actual == target:
            continue
        # 目标名已被其它列占用则跳过，避免 silent 覆盖
        if target in frame.columns and target != actual:
            continue
        if target in rename.values():
            continue
        rename[actual] = target
    if not rename:
        return frame
    return frame.rename(columns=rename)
