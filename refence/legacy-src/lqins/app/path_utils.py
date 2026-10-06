# -*- coding: utf-8 -*-
"""路径解析与容器虚拟路径转换"""

from pathlib import Path
from typing import Dict


def get_virtual_roots(project_root: Path) -> Dict[str, Path]:
    project_root = project_root.resolve()
    return {
        '/app': project_root,
        '/data': (project_root / 'data').resolve(),
    }


def resolve_runtime_path(path_str: str, default_path: str, project_root: Path) -> Path:
    """将配置路径解析为当前运行环境下的真实绝对路径。"""
    normalized_path = str(path_str or default_path).strip() or default_path
    normalized_virtual_path = normalized_path.replace('\\', '/').rstrip('/')
    virtual_roots = get_virtual_roots(project_root)

    for virtual_root, real_root in virtual_roots.items():
        if normalized_virtual_path == virtual_root:
            return real_root.resolve()
        if normalized_virtual_path.startswith(f'{virtual_root}/'):
            suffix = normalized_virtual_path[len(virtual_root) + 1:]
            return (real_root / Path(suffix)).resolve()

    path_obj = Path(normalized_path)
    if not path_obj.is_absolute():
        path_obj = (project_root / path_obj).resolve()
    return path_obj.resolve()


def to_virtual_path(actual_path: Path, project_root: Path) -> str:
    """将真实路径转换为容器适用的虚拟路径。"""
    actual_path = actual_path.resolve()
    virtual_roots = get_virtual_roots(project_root)
    ordered_roots = sorted(
        virtual_roots.items(),
        key=lambda item: len(str(item[1].resolve())),
        reverse=True,
    )
    for virtual_root, real_root in ordered_roots:
        try:
            relative_path = actual_path.relative_to(real_root.resolve())
            relative_text = relative_path.as_posix()
            return virtual_root if relative_text in ('', '.') else f'{virtual_root}/{relative_text}'
        except ValueError:
            continue
    return actual_path.as_posix()


def resolve_image_view_path(path_str: str, project_root: Path) -> Path:
    """将数据库/URL 中的图片路径解析为当前机器可读的真实路径。

    兼容 Docker 虚拟路径（/data、/app）、相对路径，以及从其它机器
    复制数据库后残留的 Windows/Linux 绝对路径（按 data/source、data/archive 锚点重映射）。
    """
    raw = str(path_str or '').strip()
    if not raw:
        raise ValueError('图片路径为空')

    normalized = raw.replace('\\', '/')

    if normalized.startswith('/data/') or normalized == '/data':
        return resolve_runtime_path(normalized, 'data/archive', project_root)
    if normalized.startswith('/app/') or normalized == '/app':
        return resolve_runtime_path(normalized, 'data/archive', project_root)

    lower = normalized.lower()
    for anchor in ('data/archive/', 'data/source/'):
        idx = lower.find(anchor)
        if idx >= 0:
            relative = normalized[idx:]
            return resolve_runtime_path(relative, 'data/archive', project_root)

    candidate = resolve_runtime_path(raw, 'data/archive', project_root)
    if candidate.exists():
        return candidate

    path_obj = Path(raw)
    if path_obj.is_absolute():
        return path_obj.resolve()
    return candidate


def normalize_config_path_display(path_str: str, default_path: str, project_root: Path) -> str:
    """将配置值规范为 UI 展示的虚拟路径（优先 /data、/app）。"""
    configured = str(path_str or default_path).strip() or default_path
    normalized = configured.replace('\\', '/').rstrip('/')

    if normalized.startswith('/app') or normalized.startswith('/data'):
        return normalized

    if not Path(configured).is_absolute():
        relative = normalized.lstrip('./')
        if relative.startswith('data/'):
            return f'/{relative}'
        if relative:
            return f'/app/{relative}'
        return default_path.replace('\\', '/')

    return to_virtual_path(
        resolve_runtime_path(configured, default_path, project_root),
        project_root,
    )
