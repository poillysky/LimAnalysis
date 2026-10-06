"""注塑机图片：按项目 / 机台 / 穴位 / 日期查阅磁盘照片。"""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.core.db import MetaSession
from app.core.meta_init import INSPECTION_KEY, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.projects import get_project, load_projects

CAVITY_LETTERS = frozenset("ABCDEFGHJKLMNPQR")
CAVITY_ORDER = list("ABCDEFGHJKLMNPQR")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
TZ = ZoneInfo("Asia/Shanghai")
VIEWER_STATUSES = ["OK", "定位NG", "底涂不良", "无料NG", "扫码不良", "相机掉线"]
PHOTO_SOURCES = ("mold", "appearance")
SOURCE_ROOT_KEYS = {
    "mold": "mold_root_path",
    "appearance": "appearance_root_path",
}
SOURCE_LABELS = {
    "mold": "注塑机",
    "appearance": "自动外观",
}
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


def _session():
    init_meta_store()
    return MetaSession()


def today_str() -> str:
    return datetime.now(TZ).strftime("%Y%m%d")


def load_settings() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, INSPECTION_KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()
    return {
        "mold_root_path": str(
            value.get("mold_root_path") or value.get("root_path") or ""
        ).strip(),
        "appearance_root_path": str(value.get("appearance_root_path") or "").strip(),
    }


def save_settings(data: dict) -> dict:
    current = load_settings()
    for key in SOURCE_ROOT_KEYS.values():
        if key in data and data[key] is not None:
            current[key] = str(data[key]).strip()
    db = _session()
    try:
        row = db.get(MetaSetting, INSPECTION_KEY)
        if row is None:
            db.add(MetaSetting(key=INSPECTION_KEY, value=current))
        else:
            row.value = current
        db.commit()
        return current
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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


def _photo_source(raw: str | None) -> str:
    source = str(raw or "mold").strip().lower() or "mold"
    if source not in PHOTO_SOURCES:
        raise ValueError("未知图片来源")
    return source


def _root(source: str = "mold") -> Path:
    kind = _photo_source(source)
    settings = load_settings()
    raw = settings[SOURCE_ROOT_KEYS[kind]]
    label = SOURCE_LABELS[kind]
    if not raw:
        raise ValueError(f"请先配置{label}照片根目录")
    path = Path(raw)
    if not path.is_absolute():
        from app.core.config import settings as app_settings

        path = app_settings.REPO_ROOT / path
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"{label}照片目录不存在：{path}")
    return path


def extract_cavity(filename: str) -> str:
    stem = Path(filename).stem
    tail = stem.rsplit(",", 1)[-1].strip().upper()
    return tail if tail in CAVITY_LETTERS else ""


def extract_status(filename: str) -> str:
    stem = Path(filename).stem
    head = stem.split(",", 1)[0].strip()
    return head if head in VIEWER_STATUSES else ""


def _project_folder_names(project: dict) -> list[str]:
    names = []
    for key in ("display_name", "project_id", "sfc_code", "prefix"):
        text = str(project.get(key) or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _machine_context(root: Path, project: dict, machine: str) -> tuple[Path, str]:
    source = (root / machine).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("机台路径非法") from exc
    if source.is_dir():
        return source, "source"
    for name in _project_folder_names(project):
        archive = (root / name / machine).resolve()
        try:
            archive.relative_to(root)
        except ValueError:
            continue
        if archive.is_dir():
            return archive, "archive"
        flat = (root / name).resolve()
        try:
            flat.relative_to(root)
        except ValueError:
            continue
        if flat.is_dir() and any(
            item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES for item in flat.iterdir()
        ):
            return flat, "flat"
    return source, "source"


def _to_client_image(item: dict, root: Path, source: str) -> dict | None:
    raw = Path(str(item.get("path") or ""))
    try:
        resolved = raw.resolve()
        rel = resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None
    return {
        "id": rel,
        "machine": item["machine"],
        "cavity": item["cavity"],
        "filename": item["filename"],
        "date_str": item["date_str"],
        "rel_path": rel,
        "status": extract_status(item.get("filename") or "")
        or str(item.get("status") or "").strip(),
        "camera": str(item.get("camera") or item.get("cavity") or ""),
        "view_url": (
            f"/api/v1/inspection/image?source={source}&rel={quote(rel, safe='')}"
        ),
    }


def _enabled_project(project_id: str) -> dict:
    project = get_project(project_id)
    if project is None or not project.get("enabled", True):
        raise ValueError("项目不存在")
    return project


def _child_dir_names(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    names = []
    try:
        for item in path.iterdir():
            if _is_listed_dir(item):
                names.append(item.name)
    except OSError:
        return []
    return sorted(names, key=str.lower)


def _appearance_project_dir(root: Path, project: dict) -> Path:
    for name in _project_folder_names(project):
        folder = (root / name).resolve()
        try:
            folder.relative_to(root)
        except ValueError:
            continue
        if folder.is_dir():
            return folder
    raise ValueError("根目录下没有该项目文件夹")


def _under_root(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root)
    return resolved


def list_appearance_folders(project_id: str, tester: str = "") -> dict:
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    testers = _child_dir_names(project_dir)
    tester_name = str(tester or "").strip()
    cameras: list[str] = []
    if tester_name:
        tester_dir = _under_root(root, project_dir / tester_name)
        cameras = _child_dir_names(tester_dir)
    return {
        "project_id": project["project_id"],
        "project_folder": project_dir.name,
        "testers": testers,
        "cameras": cameras,
        "layout": "project/tester/camera/date",
    }


def _appearance_date_names(camera_dir: Path) -> list[str]:
    names = _child_dir_names(camera_dir)
    digits = [name for name in names if name.isdigit()]
    ordered = digits or names
    return sorted(ordered, reverse=True)


def list_appearance_dates(project_id: str, tester: str, camera: str) -> dict:
    tester_name = str(tester or "").strip()
    camera_name = str(camera or "").strip()
    if not tester_name or not camera_name:
        raise ValueError("请选择测试机和相机")
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    camera_dir = _under_root(root, project_dir / tester_name / camera_name)
    today = today_str()
    ordered = _appearance_date_names(camera_dir) if camera_dir.is_dir() else []
    default_date = today if today in ordered else (ordered[0] if ordered else "")
    return {
        "dates": ordered,
        "today": today,
        "default_date": default_date,
        "layout": "project/tester/camera/date",
        "testers": _child_dir_names(project_dir),
        "cameras": _child_dir_names(_under_root(root, project_dir / tester_name)),
    }


def list_appearance_images(
    project_id: str, tester: str, camera: str, date_str: str
) -> dict:
    tester_name = str(tester or "").strip()
    camera_name = str(camera or "").strip()
    day = str(date_str or "").strip()
    if not tester_name or not camera_name or not day:
        raise ValueError("请选择测试机、相机和日期")
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    date_dir = _under_root(root, project_dir / tester_name / camera_name / day)
    raw_items: list[dict] = []
    if date_dir.is_dir():
        try:
            entries = list(date_dir.iterdir())
        except OSError:
            entries = []
        for image_file in entries:
            if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                stat = image_file.stat()
            except OSError:
                continue
            raw_items.append(
                {
                    "machine": tester_name,
                    "cavity": camera_name,
                    "camera": camera_name,
                    "filename": image_file.name,
                    "date_str": day,
                    "path": str(image_file.resolve()),
                    "mtime": stat.st_mtime,
                }
            )
    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items:
        client = _to_client_image(item, root, "appearance")
        if client:
            images.append(client)
    return {
        "project_id": project["project_id"],
        "project_name": project["display_name"],
        "machine": tester_name,
        "cavity": camera_name,
        "camera": camera_name,
        "date_str": day,
        "layout": "project/tester/camera/date",
        "total_count": len(images),
        "images": images,
    }


def search_appearance_images(project_id: str, query: str, limit: int = 80) -> dict:
    needle = _filename_needle(query)
    if not needle:
        raise ValueError("请扫码或输入文件名")
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    raw_items: list[dict] = []
    visited = 0
    max_visit = 30000
    for dirpath, _dirnames, filenames in os.walk(project_dir):
        if len(raw_items) >= limit or visited >= max_visit:
            break
        for filename in filenames:
            visited += 1
            if visited > max_visit or len(raw_items) >= limit:
                break
            if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if needle not in filename.lower():
                continue
            image_file = Path(dirpath) / filename
            try:
                resolved = image_file.resolve()
                resolved.relative_to(root)
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            rel = resolved.relative_to(project_dir)
            parts = rel.parts
            tester_name = parts[0] if len(parts) >= 4 else ""
            camera_name = parts[1] if len(parts) >= 4 else ""
            date_name = parts[2] if len(parts) >= 4 else ""
            if len(parts) == 3:
                tester_name, camera_name, date_name = parts[0], parts[1], ""
            raw_items.append(
                {
                    "machine": tester_name,
                    "cavity": camera_name,
                    "camera": camera_name,
                    "filename": filename,
                    "date_str": date_name
                    or datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d"),
                    "path": str(resolved),
                    "mtime": stat.st_mtime,
                }
            )
    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items[:limit]:
        client = _to_client_image(item, root, "appearance")
        if client:
            images.append(client)
    return {
        "project_id": project["project_id"],
        "project_name": project["display_name"],
        "query": needle,
        "total_count": len(images),
        "images": images,
    }


def list_viewer_dates(
    project_id: str, machine: str, source: str = "mold", camera: str = ""
) -> dict:
    if _photo_source(source) == "appearance":
        return list_appearance_dates(project_id, machine, camera)
    project = _enabled_project(project_id)
    machine = str(machine or "").strip()
    if not machine:
        raise ValueError("请选择机台")
    root = _root(source)
    today = today_str()
    machine_dir, layout = _machine_context(root, project, machine)
    dates: set[str] = set()
    if not machine_dir.exists() or not machine_dir.is_dir():
        return {"dates": [], "today": today, "default_date": ""}
    if layout == "source":
        for item in machine_dir.iterdir():
            if item.is_dir() and item.name.isdigit():
                dates.add(item.name)
    elif layout == "archive":
        for point_dir in machine_dir.iterdir():
            if not point_dir.is_dir():
                continue
            for date_dir in point_dir.iterdir():
                if date_dir.is_dir() and date_dir.name.isdigit():
                    dates.add(date_dir.name)
    else:
        for image_file in machine_dir.iterdir():
            if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                stamp = datetime.fromtimestamp(image_file.stat().st_mtime)
            except OSError:
                continue
            dates.add(stamp.strftime("%Y%m%d"))
    ordered = sorted(dates, reverse=True)
    default_date = today if today in ordered else (ordered[0] if ordered else "")
    return {
        "dates": ordered,
        "today": today,
        "default_date": default_date,
        "layout": layout,
        "cavities": list(CAVITY_ORDER),
        "statuses": list(VIEWER_STATUSES),
    }


def list_viewer_images(
    project_id: str,
    machine: str,
    cavity: str,
    date_str: str,
    status: str = "OK",
    source: str = "mold",
) -> dict:
    project = _enabled_project(project_id)
    machine = str(machine or "").strip()
    cavity_name = str(cavity or "").strip()
    date_str = str(date_str or "").strip()
    status_name = str(status or "OK").strip() or "OK"
    kind = _photo_source(source)
    if kind == "appearance":
        return list_appearance_images(project_id, machine, cavity_name, date_str)
    cavity = cavity_name.upper()
    if not machine or not date_str:
        raise ValueError("请选择机台和日期")
    if cavity not in CAVITY_LETTERS:
        raise ValueError("穴位无效")
    if status_name not in VIEWER_STATUSES:
        raise ValueError("状态无效")
    root = _root(kind)
    machine_dir, layout = _machine_context(root, project, machine)
    project_name = project["display_name"]
    raw_items: list[dict] = []

    if not machine_dir.exists() or not machine_dir.is_dir():
        return {
            "images": [],
            "total_count": 0,
            "machine": machine,
            "cavity": cavity,
            "date_str": date_str,
            "status": status_name,
            "layout": layout,
        }

    if layout == "flat":
        for image_file in machine_dir.iterdir():
            if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            detected_point = extract_cavity(image_file.name)
            if detected_point and detected_point != cavity:
                continue
            detected_status = extract_status(image_file.name)
            if detected_status and detected_status != status_name:
                continue
            try:
                stat = image_file.stat()
            except OSError:
                continue
            file_date = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d")
            if file_date != date_str:
                continue
            raw_items.append(
                {
                    "machine": machine,
                    "cavity": cavity,
                    "filename": image_file.name,
                    "date_str": date_str,
                    "path": str(image_file.resolve()),
                    "mtime": stat.st_mtime,
                }
            )
    else:
        search_dirs: list[Path] = []
        if layout == "source":
            point_dir = machine_dir / date_str / cavity
            status_dir = point_dir / status_name
            if status_dir.is_dir():
                search_dirs = [status_dir]
            elif point_dir.is_dir():
                search_dirs = [point_dir]
        else:
            direct = machine_dir / cavity / date_str
            if direct.is_dir():
                search_dirs = [direct]
            else:
                for point_dir in machine_dir.iterdir():
                    if not point_dir.is_dir():
                        continue
                    date_dir = point_dir / date_str
                    if date_dir.is_dir():
                        search_dirs.append(date_dir)
        seen: set[str] = set()
        for search_dir in search_dirs:
            try:
                entries = list(search_dir.iterdir())
            except OSError:
                continue
            for image_file in entries:
                if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                if layout == "archive":
                    detected_status = extract_status(image_file.name)
                    if detected_status and detected_status != status_name:
                        continue
                    detected_point = extract_cavity(image_file.name)
                    if detected_point and detected_point != cavity:
                        continue
                key = str(image_file.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    stat = image_file.stat()
                except OSError:
                    continue
                raw_items.append(
                    {
                        "machine": machine,
                        "cavity": cavity,
                        "filename": image_file.name,
                        "date_str": date_str,
                        "path": key,
                        "mtime": stat.st_mtime,
                    }
                )

    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items:
        client = _to_client_image(item, root, kind)
        if client:
            images.append(client)
    return {
        "project_id": project["project_id"],
        "project_name": project_name,
        "machine": machine,
        "cavity": cavity,
        "date_str": date_str,
        "status": status_name,
        "layout": layout,
        "total_count": len(images),
        "images": images,
    }


def _filename_needle(query: str) -> str:
    text = str(query or "").strip().replace("\\", "/")
    if not text:
        return ""
    name = Path(text.split("/")[-1]).name
    return name.lower()


def search_viewer_images(
    project_id: str, query: str, limit: int = 80, source: str = "mold"
) -> dict:
    needle = _filename_needle(query)
    if not needle:
        raise ValueError("请扫码或输入文件名")
    project = _enabled_project(project_id)
    kind = _photo_source(source)
    if kind == "appearance":
        return search_appearance_images(project_id, query, limit)
    root = _root(kind)
    machines = [str(code).strip() for code in (project.get("machines") or []) if str(code).strip()]
    machine_set = set(machines)
    scan_roots: list[tuple[Path, str]] = []
    if machines:
        for machine in machines:
            machine_dir, _layout = _machine_context(root, project, machine)
            if machine_dir.is_dir():
                scan_roots.append((machine_dir, machine))
    else:
        for name in _project_folder_names(project):
            folder = (root / name).resolve()
            try:
                folder.relative_to(root)
            except ValueError:
                continue
            if folder.is_dir():
                scan_roots.append((folder, ""))
        if not scan_roots:
            scan_roots.append((root, ""))

    raw_items: list[dict] = []
    visited = 0
    max_visit = 30000
    for base, default_machine in scan_roots:
        if len(raw_items) >= limit or visited >= max_visit:
            break
        for dirpath, _dirnames, filenames in os.walk(base):
            if len(raw_items) >= limit or visited >= max_visit:
                break
            for filename in filenames:
                visited += 1
                if visited > max_visit or len(raw_items) >= limit:
                    break
                suffix = Path(filename).suffix.lower()
                if suffix not in IMAGE_SUFFIXES:
                    continue
                if needle not in filename.lower():
                    continue
                image_file = Path(dirpath) / filename
                try:
                    resolved = image_file.resolve()
                    resolved.relative_to(root)
                    stat = resolved.stat()
                except (OSError, ValueError):
                    continue
                rel = resolved.relative_to(root)
                machine = default_machine
                cavity = extract_cavity(filename)
                status_name = extract_status(filename)
                date_str = ""
                for part in rel.parts:
                    if part in machine_set:
                        machine = part
                    if len(part) == 8 and part.isdigit():
                        date_str = part
                    if not cavity and part.upper() in CAVITY_LETTERS and len(part) == 1:
                        cavity = part.upper()
                    if not status_name and part in VIEWER_STATUSES:
                        status_name = part
                if not date_str:
                    date_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d")
                raw_items.append(
                    {
                        "machine": machine or (rel.parts[0] if rel.parts else ""),
                        "cavity": cavity or "A",
                        "filename": filename,
                        "date_str": date_str,
                        "status": status_name or "OK",
                        "path": str(resolved),
                        "mtime": stat.st_mtime,
                    }
                )

    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items[:limit]:
        client = _to_client_image(item, root, kind)
        if client:
            images.append(client)
    return {
        "project_id": project["project_id"],
        "project_name": project["display_name"],
        "query": needle,
        "total_count": len(images),
        "images": images,
    }


def resolve_image(rel: str, source: str = "mold") -> Path:
    root = _root(source)
    target = (root / Path(str(rel or "").replace("\\", "/"))).resolve()
    target.relative_to(root)
    if not target.is_file():
        raise ValueError("图片不存在")
    return target


def image_response(rel: str, source: str = "mold"):
    from fastapi.responses import FileResponse

    path = resolve_image(rel, source)
    mime, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=mime or "application/octet-stream")

def list_enabled_projects() -> list[dict]:
    return [
        {
            "project_id": item["project_id"],
            "display_name": item["display_name"],
            "machines": list(item.get("machines") or []),
        }
        for item in load_projects()
        if item.get("enabled", True)
    ]


def bootstrap() -> dict:
    settings = load_settings()
    return {
        "projects": list_enabled_projects(),
        "settings": settings,
        "cavities": list(CAVITY_ORDER),
        "statuses": list(VIEWER_STATUSES),
        "ready": {
            "mold": bool(settings.get("mold_root_path")),
            "appearance": bool(settings.get("appearance_root_path")),
        },
    }
