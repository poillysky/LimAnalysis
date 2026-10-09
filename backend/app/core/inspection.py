"""注塑机图片：按项目 / 机台 / 穴位 / 日期查阅磁盘照片。"""

from __future__ import annotations

import mimetypes
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text

from app.core import db as stores
from app.core.appearance_index import (
    appearance_index_has_rows,
    appearance_index_is_fresh,
    building_project,
    drop_files_by_rel_paths,
    drop_view_dir_index,
    ensure_view_dir_indexed,
    get_appearance_index_status,
    is_appearance_index_building,
    prune_project_index,
    prune_windows_for_dates,
    query_files_by_needle,
    query_files_by_sns,
    schedule_appearance_index_build,
    schedule_quiet_index_job,
)
from app.core.db import MetaSession
from app.core.meta_init import INSPECTION_KEY, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.projects import get_project, load_projects, load_system_defaults
from app.core.sql_ident import ident, q, table_name

CAVITY_LETTERS = frozenset("ABCDEFGHJKLMNPQR")
CAVITY_ORDER = list("ABCDEFGHJKLMNPQR")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
TZ = ZoneInfo("Asia/Shanghai")
VIEWER_STATUSES = ["OK", "定位NG", "底涂不良", "无料NG", "扫码不良", "相机掉线"]
PHOTO_SOURCES = ("mold", "appearance")
APPEARANCE_DIMS = ("tester", "mold")
SOURCE_ROOT_KEYS = {
    "mold": "mold_root_path",
    "appearance": "appearance_root_path",
}
SOURCE_LABELS = {
    "mold": "注塑机",
    "appearance": "自动外观",
}
# 真实磁盘：项目 / 测试机 / GVIMAGES / LIM外观检测 / YYYY.MM.DD / 截图 / 视角 / 文件
APPEARANCE_FIXED_SEGMENTS = ("GVIMAGES", "LIM外观检测")
APPEARANCE_SHOT_DIR = "截图"
APPEARANCE_LAYOUT = "project/tester/GVIMAGES/LIM外观检测/date/截图/view"
# 注塑生产日取 SN；外观可能当天/隔天/多日后才测，按生产日起向后扫
APPEARANCE_MOLD_LAYOUT = "raw(生产日×机台×穴位→SN) + appearance_sn_index"
APPEARANCE_SN_LIMIT = 5000
APPEARANCE_MOLD_LOOKAHEAD_DAYS = 7
APPEARANCE_MOLD_DATE_LIMIT = 366
RAW_TIME_COL_CANDIDATES = (
    "ServerTime",
    "ingested_at",
    "检测时间",
    "生产时间",
    "时间",
    "created_at",
)
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
    stem = Path(filename).stem
    head = stem.split(",", 1)[0].strip()
    if head in VIEWER_STATUSES:
        return head
    for status in VIEWER_STATUSES:
        if status and status in stem:
            return status
    return ""


def _resolve_machine_token(token: str, machine_set: set[str]) -> str:
    raw = str(token or "").strip()
    if not raw or not machine_set:
        return ""
    if raw in machine_set:
        return raw
    lower_map = {m.lower(): m for m in machine_set}
    return lower_map.get(raw.lower(), "")


def _project_folder_names(project: dict) -> list[str]:
    """外观/归档目录名候选：项目显示名、编号等（去空白后自动对磁盘文件夹模糊匹配）。"""
    names: list[str] = []
    for key in ("display_name", "project_id", "sfc_code", "prefix"):
        text = str(project.get(key) or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _fold_folder_token(name: str) -> str:
    """Eel spk / Eelspkr / eel_spkr → eelspk(r)，只留小写字母数字。"""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _appearance_match_score(project_token: str, folder_token: str) -> int:
    """同名或唯一前缀（Eelspkr↔Eel spk）；过短不配，避免误伤。"""
    if not project_token or not folder_token:
        return 0
    if project_token == folder_token:
        return 1000 + len(folder_token)
    shorter, longer = (
        (project_token, folder_token)
        if len(project_token) <= len(folder_token)
        else (folder_token, project_token)
    )
    if len(shorter) < 4:
        return 0
    if longer.startswith(shorter):
        return 500 + len(shorter)
    return 0


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
    tried = _project_folder_names(project)
    disk_names = _child_dir_names(root)
    lower_map = {name.lower(): name for name in disk_names}

    for name in tried:
        folder = (root / name).resolve()
        try:
            folder.relative_to(root)
        except ValueError:
            continue
        if folder.is_dir():
            return folder
        alias = lower_map.get(name.lower())
        if alias:
            return _under_root(root, root / alias)

    # 去空格/符号后匹配：Eelspkr → Eel spk；多候选时取分最高且唯一
    best_name = ""
    best_score = 0
    tied = False
    project_tokens = [_fold_folder_token(name) for name in tried if _fold_folder_token(name)]
    for disk_name in disk_names:
        folder_token = _fold_folder_token(disk_name)
        score = max(
            (_appearance_match_score(token, folder_token) for token in project_tokens),
            default=0,
        )
        if score <= 0:
            continue
        if score > best_score:
            best_score = score
            best_name = disk_name
            tied = False
        elif score == best_score:
            tied = True
    if best_name and not tied:
        return _under_root(root, root / best_name)

    available = "、".join(disk_names) or "（空）"
    wanted = "、".join(tried) or "（无）"
    raise ValueError(
        f"根目录下没有该项目文件夹。已试：{wanted}；现有：{available}。"
        f"请把项目名写成与文件夹接近的形式（如 Eelspkr 对应 Eel spk）。"
    )


def _under_root(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(root)
    return resolved


def _appearance_session_dir(tester_dir: Path) -> Path:
    """测试机下固定中间层：GVIMAGES / LIM外观检测。"""
    path = tester_dir
    for segment in APPEARANCE_FIXED_SEGMENTS:
        path = path / segment
    return path


def _appearance_date_sort_key(name: str) -> str:
    """把 2026.10.07 / 20261007 / 2026-10-07 归一成 YYYYMMDD 便于倒序。"""
    text = str(name or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return text


def _appearance_is_date_dir(name: str) -> bool:
    return bool(re.fullmatch(r"\d{8}", name) or re.fullmatch(r"\d{4}[.\-]\d{2}[.\-]\d{2}", name))


def _appearance_date_aliases(date_str: str) -> list[str]:
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


def _appearance_resolve_date_dir(session_dir: Path, date_str: str) -> Path | None:
    if not session_dir.is_dir():
        return None
    for name in _appearance_date_aliases(date_str):
        candidate = session_dir / name
        if candidate.is_dir():
            return candidate
    want = _appearance_date_sort_key(date_str)
    if not want:
        return None
    try:
        for item in session_dir.iterdir():
            if item.is_dir() and _appearance_date_sort_key(item.name) == want:
                return item
    except OSError:
        return None
    return None


def _appearance_shot_dir(date_dir: Path) -> Path:
    return date_dir / APPEARANCE_SHOT_DIR


def _appearance_view_dir(date_dir: Path, view: str) -> Path:
    return _appearance_shot_dir(date_dir) / view


def _appearance_list_date_names(session_dir: Path, view: str = "") -> list[str]:
    if not session_dir.is_dir():
        return []
    view_name = str(view or "").strip()
    names: list[str] = []
    try:
        for item in session_dir.iterdir():
            if not _is_listed_dir(item) or not _appearance_is_date_dir(item.name):
                continue
            if view_name:
                view_dir = _appearance_view_dir(item, view_name)
                if not view_dir.is_dir():
                    continue
            names.append(item.name)
    except OSError:
        return []
    return sorted(names, key=_appearance_date_sort_key, reverse=True)


def _appearance_list_views(session_dir: Path, date_str: str = "") -> list[str]:
    """视角在「截图」下；未指定日期时汇总该测试机全部日期的视角。"""
    if not session_dir.is_dir():
        return []
    views: set[str] = set()
    date_dirs: list[Path] = []
    if date_str:
        resolved = _appearance_resolve_date_dir(session_dir, date_str)
        if resolved is not None:
            date_dirs = [resolved]
    else:
        try:
            date_dirs = [
                item
                for item in session_dir.iterdir()
                if _is_listed_dir(item) and _appearance_is_date_dir(item.name)
            ]
        except OSError:
            return []
    for date_dir in date_dirs:
        shot = _appearance_shot_dir(date_dir)
        for name in _child_dir_names(shot):
            views.add(name)
    return sorted(views, key=str.lower)


def _appearance_parse_rel(rel: Path) -> tuple[str, str, str]:
    """从项目相对路径解析 (测试机, 日期, 视角)。"""
    parts = rel.parts
    # tester / GVIMAGES / LIM外观检测 / date / 截图 / view / file
    if len(parts) >= 7 and parts[1:3] == APPEARANCE_FIXED_SEGMENTS and parts[4] == APPEARANCE_SHOT_DIR:
        return parts[0], parts[3], parts[5]
    if len(parts) >= 4:
        return parts[0], parts[2] if len(parts) > 2 else "", parts[1]
    if len(parts) >= 2:
        return parts[0], "", parts[1] if len(parts) > 1 else ""
    return "", "", ""


def _appearance_default_date(ordered: list[str]) -> str:
    today = today_str()
    aliases = set(_appearance_date_aliases(today))
    for name in ordered:
        if name in aliases or _appearance_date_sort_key(name) in aliases:
            return name
    return ordered[0] if ordered else ""


def _appearance_dim(raw: str | None) -> str:
    dim = str(raw or "tester").strip().lower() or "tester"
    if dim not in APPEARANCE_DIMS:
        raise ValueError("未知外观查询维度")
    return dim


def _pick_raw_col(columns: list[str], *names: str) -> str | None:
    exact = {name: name for name in columns}
    lower = {name.lower(): name for name in columns}
    for name in names:
        if name in exact:
            return exact[name]
        hit = lower.get(name.lower())
        if hit:
            return hit
    return None


def _raw_table_for_project(project: dict) -> str:
    table = table_name(
        str(project.get("prefix") or ""), str(project.get("project_id") or "")
    )
    inspector = inspect(stores.raw_engine)
    table_i = ident(table)
    if inspector.has_table(table_i):
        return table_i
    if inspector.has_table(table):
        return table
    raise ValueError("原始库还没有该项目的数据表")


def _raw_layout_cols(project: dict) -> dict:
    table = _raw_table_for_project(project)
    columns = [
        str(col["name"]) for col in inspect(stores.raw_engine).get_columns(table)
    ]
    defaults = load_system_defaults()
    pk_name = str((defaults.get("unique_key") or {}).get("column") or "FCoverSN").strip()
    sn_col = _pick_raw_col(columns, pk_name, "FCoverSN", "前盖码", "SN", "sn")
    machine_col = _pick_raw_col(columns, "机台")
    cavity_col = _pick_raw_col(columns, "模穴", "模具模穴")
    time_col = _pick_raw_col(columns, *RAW_TIME_COL_CANDIDATES)
    if not sn_col or not machine_col or not cavity_col:
        raise ValueError("原始表缺少 SN / 机台 / 模穴 字段，无法按注塑机维度查图")
    return {
        "table": table,
        "sn": sn_col,
        "machine": machine_col,
        "cavity": cavity_col,
        "time": time_col,
    }


def _ymd_only(date_str: str) -> str:
    key = _appearance_date_sort_key(date_str)
    return key if len(key) == 8 else ""


def _ymd_range(start_ymd: str, days: int) -> list[str]:
    """含起点共 days+1 天，格式 YYYYMMDD。"""
    ymd = _ymd_only(start_ymd)
    if not ymd:
        return []
    start = datetime.strptime(ymd, "%Y%m%d")
    span = max(0, int(days))
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(span + 1)]


def _cavity_letter_sql(cavity_sql: str) -> str:
    return (
        f"UPPER(SUBSTRING(BTRIM(({cavity_sql})::text) "
        f"FROM CHAR_LENGTH(BTRIM(({cavity_sql})::text)) FOR 1))"
    )


def _filename_has_sn(filename: str, sns: set[str]) -> str:
    """文件名里是否含目标 SN；命中则返回该 SN，否则空串。"""
    if not sns:
        return ""
    stem = Path(filename).stem
    if stem.startswith("截图"):
        stem = stem[2:]
    if "_" in stem:
        candidate = stem.rsplit("_", 1)[0]
        if candidate in sns:
            return candidate
    lower_name = filename.lower()
    for sn in sns:
        if sn and sn.lower() in lower_name:
            return sn
    return ""


def list_sns_for_machine_cavity(
    project: dict,
    machine: str,
    cavity_letter: str,
    *,
    date_str: str = "",
    limit: int = APPEARANCE_SN_LIMIT,
) -> list[str]:
    """从 lim_raw 按机台 × 模穴末位字母取 SN；有生产日则只取该日。"""
    machine_name = str(machine or "").strip()
    letter = str(cavity_letter or "").strip().upper()
    if not machine_name:
        raise ValueError("请选择注塑机台")
    if letter not in CAVITY_LETTERS:
        raise ValueError("穴位无效")
    layout = _raw_layout_cols(project)
    sn_sql = q(ident(layout["sn"]))
    machine_sql = q(ident(layout["machine"]))
    cavity_sql = q(ident(layout["cavity"]))
    ymd = _ymd_only(date_str)
    params: dict = {
        "machine": machine_name,
        "letter": letter,
        "lim": max(1, int(limit)),
    }
    day_clause = ""
    time_col = layout.get("time")
    if ymd and time_col:
        time_sql = q(ident(time_col))
        start = datetime.strptime(ymd, "%Y%m%d")
        end = start + timedelta(days=1)
        day_clause = (
            f" AND ({time_sql})::timestamp >= CAST(:day_start AS timestamp)"
            f" AND ({time_sql})::timestamp < CAST(:day_end AS timestamp)"
        )
        params["day_start"] = start.strftime("%Y-%m-%d %H:%M:%S")
        params["day_end"] = end.strftime("%Y-%m-%d %H:%M:%S")
    sql = text(
        f"SELECT BTRIM(({sn_sql})::text) AS sn "
        f"FROM {q(ident(layout['table']))} "
        f"WHERE BTRIM(({machine_sql})::text) = :machine "
        f"AND {_cavity_letter_sql(cavity_sql)} = :letter "
        f"AND BTRIM(({sn_sql})::text) <> '' "
        f"{day_clause}"
        f"LIMIT :lim"
    )
    with stores.raw_engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        sn = str(row[0] or "").strip()
        if not sn or sn in seen:
            continue
        seen.add(sn)
        out.append(sn)
    return out


def list_production_dates_for_machine(
    project: dict,
    machine: str,
    cavity_letter: str = "",
    *,
    limit: int = APPEARANCE_MOLD_DATE_LIMIT,
) -> list[str]:
    """注塑机维度日期列表：raw 生产日（YYYYMMDD），不是外观截图目录日。"""
    machine_name = str(machine or "").strip()
    if not machine_name:
        return []
    layout = _raw_layout_cols(project)
    time_col = layout.get("time")
    if not time_col:
        return []
    sn_sql = q(ident(layout["sn"]))
    machine_sql = q(ident(layout["machine"]))
    cavity_sql = q(ident(layout["cavity"]))
    time_sql = q(ident(time_col))
    letter = str(cavity_letter or "").strip().upper()
    params: dict = {"machine": machine_name, "lim": max(1, int(limit))}
    cavity_clause = ""
    if letter:
        if letter not in CAVITY_LETTERS:
            return []
        cavity_clause = f" AND {_cavity_letter_sql(cavity_sql)} = :letter "
        params["letter"] = letter
    sql = text(
        f"SELECT DISTINCT to_char(({time_sql})::timestamp, 'YYYYMMDD') AS d "
        f"FROM {q(ident(layout['table']))} "
        f"WHERE BTRIM(({machine_sql})::text) = :machine "
        f"AND BTRIM(({sn_sql})::text) <> '' "
        f"AND ({time_sql}) IS NOT NULL "
        f"{cavity_clause}"
        f"ORDER BY d DESC "
        f"LIMIT :lim"
    )
    with stores.raw_engine.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[str] = []
    for row in rows:
        day = str(row[0] or "").strip()
        if day and day not in out:
            out.append(day)
    return out


def _appearance_union_views(project_dir: Path) -> list[str]:
    views: set[str] = set()
    for tester_name in _child_dir_names(project_dir):
        session = _appearance_session_dir(project_dir / tester_name)
        for name in _appearance_list_views(session):
            views.add(name)
    return sorted(views, key=str.lower)


def _appearance_union_dates(project_dir: Path, view: str = "") -> list[str]:
    dates: set[str] = set()
    for tester_name in _child_dir_names(project_dir):
        session = _appearance_session_dir(project_dir / tester_name)
        for name in _appearance_list_date_names(session, view):
            dates.add(name)
    return sorted(dates, key=_appearance_date_sort_key, reverse=True)


def list_appearance_folders(
    project_id: str, tester: str = "", dim: str = "tester"
) -> dict:
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    kind = _appearance_dim(dim)
    if kind == "mold":
        machines = [
            str(code).strip()
            for code in (project.get("machines") or [])
            if str(code).strip()
        ]
        return {
            "project_id": project["project_id"],
            "project_folder": project_dir.name,
            "dim": "mold",
            "machines": machines,
            "cavities": list(CAVITY_ORDER),
            "testers": [],
            "cameras": _appearance_union_views(project_dir),
            "layout": APPEARANCE_MOLD_LAYOUT,
        }
    testers = _child_dir_names(project_dir)
    tester_name = str(tester or "").strip()
    cameras: list[str] = []
    if tester_name:
        tester_dir = _under_root(root, project_dir / tester_name)
        cameras = _appearance_list_views(_appearance_session_dir(tester_dir))
    return {
        "project_id": project["project_id"],
        "project_folder": project_dir.name,
        "dim": "tester",
        "testers": testers,
        "cameras": cameras,
        "machines": [],
        "cavities": [],
        "layout": APPEARANCE_LAYOUT,
    }


def list_appearance_dates(
    project_id: str, tester: str, camera: str, dim: str = "tester"
) -> dict:
    camera_name = str(camera or "").strip()
    kind = _appearance_dim(dim)
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    today = today_str()
    if kind == "mold":
        if not camera_name:
            raise ValueError("请选择视角")
        machine_name = str(tester or "").strip()
        ordered: list[str] = []
        if machine_name:
            try:
                ordered = list_production_dates_for_machine(project, machine_name)
            except ValueError:
                ordered = []
        if not ordered:
            # 无生产时间列或该机台尚无 raw 时，退回外观目录日（查图仍会向后扫）
            ordered = _appearance_union_dates(project_dir, camera_name)
        machines = [
            str(code).strip()
            for code in (project.get("machines") or [])
            if str(code).strip()
        ]
        return {
            "dates": ordered,
            "today": today,
            "default_date": _appearance_default_date(ordered),
            "layout": APPEARANCE_MOLD_LAYOUT,
            "dim": "mold",
            "date_kind": "production",
            "lookahead_days": APPEARANCE_MOLD_LOOKAHEAD_DAYS,
            "machines": machines,
            "cavities": list(CAVITY_ORDER),
            "cameras": _appearance_union_views(project_dir),
            "testers": [],
        }
    tester_name = str(tester or "").strip()
    if not tester_name or not camera_name:
        raise ValueError("请选择测试机和视角")
    tester_dir = _under_root(root, project_dir / tester_name)
    session_dir = _appearance_session_dir(tester_dir)
    ordered = _appearance_list_date_names(session_dir, camera_name)
    return {
        "dates": ordered,
        "today": today,
        "default_date": _appearance_default_date(ordered),
        "layout": APPEARANCE_LAYOUT,
        "dim": "tester",
        "testers": _child_dir_names(project_dir),
        "cameras": _appearance_list_views(session_dir),
        "machines": [],
        "cavities": [],
    }


def _ensure_appearance_index_windows_body(
    project_key: str,
    project_dir: Path,
    *,
    view: str,
    date_ymds: list[str],
) -> None:
    """把各测试机在给定日期×视角刷进索引（安静增量，不标 building）。"""
    view_name = str(view or "").strip()
    if not view_name:
        return
    live: set[tuple[str, str, str]] = set()
    day_keys = [_ymd_only(d) or str(d).strip() for d in date_ymds if str(d).strip()]
    for tester_name in _child_dir_names(project_dir):
        session_dir = _appearance_session_dir(project_dir / tester_name)
        for scan_day in date_ymds:
            date_dir = _appearance_resolve_date_dir(session_dir, scan_day)
            ymd = (
                (_ymd_only(date_dir.name) if date_dir is not None else "")
                or _ymd_only(scan_day)
                or str(scan_day).strip()
            )
            if date_dir is None:
                if ymd:
                    drop_view_dir_index(
                        project_key,
                        tester=tester_name,
                        date_ymd=ymd,
                        view=view_name,
                    )
                continue
            view_dir = _appearance_view_dir(date_dir, view_name)
            if not view_dir.is_dir():
                drop_view_dir_index(
                    project_key,
                    tester=tester_name,
                    date_ymd=ymd,
                    view=view_name,
                )
                continue
            ensure_view_dir_indexed(
                project_key,
                project_dir,
                tester=tester_name,
                date_ymd=ymd,
                date_str=date_dir.name,
                view=view_name,
                view_dir=view_dir,
            )
            live.add((tester_name, ymd, view_name))
    prune_windows_for_dates(
        project_key, view=view_name, date_ymds=day_keys, live_windows=live
    )


def _schedule_appearance_windows(
    project_key: str,
    project_dir: Path,
    *,
    view: str,
    date_ymds: list[str],
) -> None:
    """查图请求里只排队后台增量，绝不同步扫盘。"""
    view_name = str(view or "").strip()
    days = [str(d).strip() for d in date_ymds if str(d).strip()]
    if not view_name or not days:
        return
    job_key = f"{project_key}|win|{view_name}|{','.join(days)}"
    schedule_quiet_index_job(
        job_key,
        lambda: _ensure_appearance_index_windows_body(
            project_key, project_dir, view=view_name, date_ymds=days
        ),
    )


def _ensure_appearance_index_project_body(
    project_key: str, project_dir: Path
) -> None:
    """索引现存目录并 prune 孤儿窗口（调用方负责 building 标记）。"""
    live: set[tuple[str, str, str]] = set()
    for tester_name in _child_dir_names(project_dir):
        session_dir = _appearance_session_dir(project_dir / tester_name)
        if not session_dir.is_dir():
            continue
        try:
            date_dirs = [
                item
                for item in session_dir.iterdir()
                if _is_listed_dir(item) and _appearance_is_date_dir(item.name)
            ]
        except OSError:
            continue
        for date_dir in date_dirs:
            ymd = _ymd_only(date_dir.name)
            if not ymd:
                continue
            shot = _appearance_shot_dir(date_dir)
            for view_name in _child_dir_names(shot):
                view_dir = shot / view_name
                if not view_dir.is_dir():
                    drop_view_dir_index(
                        project_key,
                        tester=tester_name,
                        date_ymd=ymd,
                        view=view_name,
                    )
                    continue
                ensure_view_dir_indexed(
                    project_key,
                    project_dir,
                    tester=tester_name,
                    date_ymd=ymd,
                    date_str=date_dir.name,
                    view=view_name,
                    view_dir=view_dir,
                )
                live.add((tester_name, ymd, view_name))
    prune_project_index(project_key, live)


def _ensure_appearance_index_project(project_key: str, project_dir: Path) -> None:
    """同步全量/增量刷项目索引。"""
    with building_project(project_key):
        _ensure_appearance_index_project_body(project_key, project_dir)


def appearance_index_status(project_id: str) -> dict:
    """外观 SN 索引状态（进页预热全量，之后增量）。"""
    project = _enabled_project(project_id)
    status = get_appearance_index_status(str(project["project_id"]))
    status["project_id"] = project["project_id"]
    status["project_name"] = project["display_name"]
    return status


def warm_appearance_index(project_id: str, *, force: bool = False) -> dict:
    """进外观页后台全量/增量刷；已新鲜则跳过；已在建则复用。"""
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    project_key = str(project["project_id"])
    if not force and appearance_index_is_fresh(project_key):
        status = appearance_index_status(project_id)
        status["warm_started"] = False
        status["skipped_fresh"] = True
        return status
    scheduled = schedule_appearance_index_build(
        project_key,
        lambda: _ensure_appearance_index_project_body(project_key, project_dir),
    )
    status = appearance_index_status(project_id)
    status["warm_started"] = bool(scheduled.get("started"))
    status["building"] = bool(
        status.get("building") or scheduled.get("building")
    )
    if status["building"] and status.get("status") == "empty":
        status["status"] = "building"
        status["status_label"] = "生成中"
    return status


def _kick_appearance_index_if_empty(project_key: str, project_dir: Path) -> None:
    """请求路径只负责点火，绝不同步扫盘。"""
    if appearance_index_has_rows(project_key) or is_appearance_index_building(project_key):
        return
    schedule_appearance_index_build(
        project_key,
        lambda: _ensure_appearance_index_project_body(project_key, project_dir),
    )


def list_appearance_images_by_mold(
    project_id: str, machine: str, cavity: str, camera: str, date_str: str
) -> dict:
    """注塑机维度：生产日×机台×穴位 → SN，再靠外观 SN 索引出图。"""
    machine_name = str(machine or "").strip()
    letter = str(cavity or "").strip().upper()
    camera_name = str(camera or "").strip()
    day = str(date_str or "").strip()
    if not machine_name or not letter or not camera_name or not day:
        raise ValueError("请选择注塑机台、穴位、视角和生产日")
    if letter not in CAVITY_LETTERS:
        raise ValueError("穴位无效")
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    project_key = str(project["project_id"])
    prod_ymd = _ymd_only(day) or day
    sns = list_sns_for_machine_cavity(
        project, machine_name, letter, date_str=prod_ymd
    )
    sn_set = set(sns)
    scan_days = _ymd_range(prod_ymd, APPEARANCE_MOLD_LOOKAHEAD_DAYS) or [prod_ymd]
    raw_items: list[dict] = []
    if sn_set:
        # 只查 SQLite；窗口增量丢后台，不挡本次查图
        _kick_appearance_index_if_empty(project_key, project_dir)
        _schedule_appearance_windows(
            project_key,
            project_dir,
            view=camera_name,
            date_ymds=scan_days,
        )
        hits = query_files_by_sns(
            project_key, sn_set, view=camera_name, date_ymds=scan_days
        )
        missing_rels: list[str] = []
        for hit in hits:
            rel = str(hit.get("rel_path") or "")
            abs_path = (project_dir / rel).resolve()
            try:
                abs_path.relative_to(root)
            except ValueError:
                if rel:
                    missing_rels.append(rel)
                continue
            if not abs_path.is_file():
                if rel:
                    missing_rels.append(rel)
                continue
            raw_items.append(
                {
                    "machine": machine_name,
                    "cavity": letter,
                    "camera": camera_name,
                    "filename": hit["filename"],
                    "date_str": hit["date_str"],
                    "path": str(abs_path),
                    "mtime": hit["mtime"],
                    "sn": hit["sn"],
                    "tester": hit["tester"],
                }
            )
        if missing_rels:
            drop_files_by_rel_paths(project_key, missing_rels)
    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items:
        client = _to_client_image(item, root, "appearance")
        if client:
            images.append(client)
    hint = ""
    look = APPEARANCE_MOLD_LOOKAHEAD_DAYS
    building = is_appearance_index_building(project_key)
    has_index = appearance_index_has_rows(project_key)
    if not sn_set:
        hint = f"原始库没有机台 {machine_name}、穴位 {letter}、生产日 {prod_ymd} 的 SN"
    elif not images and (building or not has_index):
        hint = "索引仍在后台生成/更新，稍后再查即可看到新图"
    elif not images:
        hint = (
            f"有 {len(sn_set)} 个生产日 SN，"
            f"但随后 {look} 天内该视角没有对应外观截图"
        )
    return {
        "project_id": project["project_id"],
        "project_name": project["display_name"],
        "dim": "mold",
        "machine": machine_name,
        "cavity": letter,
        "camera": camera_name,
        "date_str": prod_ymd,
        "date_kind": "production",
        "lookahead_days": look,
        "scan_dates": scan_days,
        "layout": APPEARANCE_MOLD_LAYOUT,
        "sn_count": len(sn_set),
        "hint": hint,
        "total_count": len(images),
        "images": images,
    }


def list_appearance_images(
    project_id: str, tester: str, camera: str, date_str: str
) -> dict:
    tester_name = str(tester or "").strip()
    camera_name = str(camera or "").strip()
    day = str(date_str or "").strip()
    if not tester_name or not camera_name or not day:
        raise ValueError("请选择测试机、视角和日期")
    project = _enabled_project(project_id)
    root = _root("appearance")
    project_dir = _appearance_project_dir(root, project)
    tester_dir = _under_root(root, project_dir / tester_name)
    session_dir = _appearance_session_dir(tester_dir)
    date_dir = _appearance_resolve_date_dir(session_dir, day)
    view_dir = _appearance_view_dir(date_dir, camera_name) if date_dir is not None else None
    disk_date = date_dir.name if date_dir is not None else day
    raw_items: list[dict] = []
    if view_dir is not None and view_dir.is_dir():
        try:
            entries = list(view_dir.iterdir())
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
                    "date_str": disk_date,
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
        "dim": "tester",
        "machine": tester_name,
        "cavity": camera_name,
        "camera": camera_name,
        "date_str": disk_date,
        "layout": APPEARANCE_LAYOUT,
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
    project_key = str(project["project_id"])
    # 扫码只查索引；空则后台点火，绝不在请求里等扫盘
    _kick_appearance_index_if_empty(project_key, project_dir)
    hits = query_files_by_needle(project_key, needle, limit=limit)
    raw_items: list[dict] = []
    missing_rels: list[str] = []
    for hit in hits:
        rel = str(hit.get("rel_path") or "")
        abs_path = (project_dir / rel).resolve()
        try:
            abs_path.relative_to(root)
        except ValueError:
            if rel:
                missing_rels.append(rel)
            continue
        if not abs_path.is_file():
            if rel:
                missing_rels.append(rel)
            continue
        raw_items.append(
            {
                "machine": hit["tester"],
                "cavity": hit["view"],
                "camera": hit["view"],
                "filename": hit["filename"],
                "date_str": hit["date_str"],
                "path": str(abs_path),
                "mtime": hit["mtime"],
                "sn": hit.get("sn") or "",
            }
        )
    if missing_rels:
        drop_files_by_rel_paths(project_key, missing_rels)
    raw_items.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    images = []
    for item in raw_items[:limit]:
        client = _to_client_image(item, root, "appearance")
        if client:
            images.append(client)
    hint = ""
    if not images and (
        is_appearance_index_building(project_key)
        or not appearance_index_has_rows(project_key)
    ):
        hint = "索引仍在后台生成，稍后再扫即可"
    return {
        "project_id": project["project_id"],
        "project_name": project["display_name"],
        "query": needle,
        "hint": hint,
        "total_count": len(images),
        "images": images,
    }


def list_viewer_dates(
    project_id: str,
    machine: str,
    source: str = "mold",
    camera: str = "",
    dim: str = "tester",
) -> dict:
    if _photo_source(source) == "appearance":
        return list_appearance_dates(project_id, machine, camera, dim=dim)
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
    dim: str = "tester",
    camera: str = "",
) -> dict:
    project = _enabled_project(project_id)
    machine = str(machine or "").strip()
    cavity_name = str(cavity or "").strip()
    date_str = str(date_str or "").strip()
    status_name = str(status or "OK").strip() or "OK"
    kind = _photo_source(source)
    if kind == "appearance":
        if _appearance_dim(dim) == "mold":
            view = str(camera or cavity_name).strip()
            return list_appearance_images_by_mold(
                project_id, machine, cavity_name, view, date_str
            )
        # tester 模式：machine=测试机，cavity=视角
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
                machine = _resolve_machine_token(default_machine, machine_set) or default_machine
                cavity = extract_cavity(filename)
                status_name = extract_status(filename)
                date_str = ""
                for part in rel.parts:
                    hit = _resolve_machine_token(part, machine_set)
                    if hit:
                        machine = hit
                    if len(part) == 8 and part.isdigit():
                        date_str = part
                    if not cavity and part.upper() in CAVITY_LETTERS and len(part) == 1:
                        cavity = part.upper()
                    if not status_name and part in VIEWER_STATUSES:
                        status_name = part
                # 文件名里也可能带机台号（扫码内容）
                stem = Path(filename).stem
                for part in re.split(r"[,_\-\s/\\]+", stem):
                    hit = _resolve_machine_token(part, machine_set)
                    if hit:
                        machine = hit
                        break
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
