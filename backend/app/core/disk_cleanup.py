"""磁盘清理：Postgres 旧行、图片目录；容量快照。CSV 成功入库后由 Worker 即时删文件。"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core import db as stores
from app.core.config import settings
from app.core.db import MetaSession
from app.core.inspection import load_settings as load_inspection_settings
from app.core.meta_init import DEFAULT_DISK_CLEANUP, DISK_CLEANUP_KEY, init_meta_store
from app.core.meta_models import MetaSetting
from app.core.sql_ident import ident, q

logger = logging.getLogger(__name__)

_BATCH = 5000
_MAX_BATCHES_PER_TABLE = 200
_TIME_CANDIDATES = ("hour", "ServerTime", "ingested_at", "etl_at", "created_at")
_DIR_SIZE_FILE_CAP = 200_000


def _session():
    init_meta_store()
    return MetaSession()


def _clamp_days(value, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(3650, n))


def _clamp_hour(value, default: int = 3) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(0, min(23, n))


def load_disk_cleanup_config() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, DISK_CLEANUP_KEY)
        stored = dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()
    merged = {**DEFAULT_DISK_CLEANUP, **stored}
    merged["enabled"] = bool(merged.get("enabled"))
    merged["db_retention_days"] = _clamp_days(
        merged.get("db_retention_days"), DEFAULT_DISK_CLEANUP["db_retention_days"]
    )
    merged["image_retention_days"] = _clamp_days(
        merged.get("image_retention_days"),
        DEFAULT_DISK_CLEANUP["image_retention_days"],
    )
    merged["run_hour"] = _clamp_hour(
        merged.get("run_hour"), DEFAULT_DISK_CLEANUP["run_hour"]
    )
    merged["last_run_time"] = str(merged.get("last_run_time") or "")
    merged["last_run_status"] = str(merged.get("last_run_status") or "")[:40]
    merged["last_run_message"] = str(merged.get("last_run_message") or "")[:500]
    result = merged.get("last_run_result")
    merged["last_run_result"] = dict(result) if isinstance(result, dict) else {}
    return merged


def save_disk_cleanup_config(data: dict) -> dict:
    current = load_disk_cleanup_config()
    if "enabled" in data and data["enabled"] is not None:
        current["enabled"] = bool(data["enabled"])
    if "db_retention_days" in data and data["db_retention_days"] is not None:
        current["db_retention_days"] = _clamp_days(
            data["db_retention_days"], current["db_retention_days"]
        )
    if "image_retention_days" in data and data["image_retention_days"] is not None:
        current["image_retention_days"] = _clamp_days(
            data["image_retention_days"], current["image_retention_days"]
        )
    if "run_hour" in data and data["run_hour"] is not None:
        current["run_hour"] = _clamp_hour(data["run_hour"], current["run_hour"])
    if "last_run_time" in data and data["last_run_time"] is not None:
        current["last_run_time"] = str(data["last_run_time"] or "")
    if "last_run_status" in data and data["last_run_status"] is not None:
        current["last_run_status"] = str(data["last_run_status"] or "")[:40]
    if "last_run_message" in data and data["last_run_message"] is not None:
        current["last_run_message"] = str(data["last_run_message"] or "")[:500]
    if "last_run_result" in data and data["last_run_result"] is not None:
        current["last_run_result"] = (
            dict(data["last_run_result"])
            if isinstance(data["last_run_result"], dict)
            else {}
        )

    db = _session()
    try:
        row = db.get(MetaSetting, DISK_CLEANUP_KEY)
        if row is None:
            db.add(MetaSetting(key=DISK_CLEANUP_KEY, value=current))
        else:
            row.value = dict(current)
        db.commit()
        return load_disk_cleanup_config()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def patch_disk_cleanup_config(data: dict) -> dict:
    return save_disk_cleanup_config(data)


def request_disk_cleanup(*, trigger: str = "manual") -> dict:
    from collector.jobs import JOB_DISK_CLEANUP, enqueue_job, find_active_job

    active = find_active_job(JOB_DISK_CLEANUP)
    if active:
        return {
            "accepted": False,
            "job_id": active["id"],
            "message": "已有磁盘清理任务排队或执行中",
            "status": active["status"],
        }
    job = enqueue_job(
        JOB_DISK_CLEANUP,
        {"trigger": trigger},
        message=f"disk_cleanup queued ({trigger})",
    )
    return {
        "accepted": True,
        "job_id": job["id"],
        "message": "已入队，等待 Worker 执行",
        "status": job["status"],
    }


def _fmt_bytes(n: int) -> str:
    size = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _disk_usage_info(path: Path) -> dict:
    info = {
        "path": str(path),
        "exists": False,
        "total": 0,
        "used": 0,
        "free": 0,
        "used_pct": None,
        "dir_bytes": None,
        "dir_files": None,
        "error": None,
    }
    try:
        if not path.exists():
            info["error"] = "路径不存在"
            return info
        info["exists"] = True
        usage = shutil.disk_usage(path if path.is_dir() else path.parent)
        info["total"] = int(usage.total)
        info["used"] = int(usage.used)
        info["free"] = int(usage.free)
        info["used_pct"] = round(100.0 * usage.used / usage.total, 1) if usage.total else None
        if path.is_dir():
            dir_bytes, dir_files = _estimate_dir_size(path)
            info["dir_bytes"] = dir_bytes
            info["dir_files"] = dir_files
    except Exception as exc:
        info["error"] = str(exc)[:200]
    return info


def _estimate_dir_size(root: Path) -> tuple[int, int]:
    total = 0
    files = 0
    try:
        for dirpath, dirnames, filenames in root.walk(on_error=lambda _e: None):
            # pathlib.Path.walk is 3.12+; project uses 3.12
            for name in filenames:
                files += 1
                if files > _DIR_SIZE_FILE_CAP:
                    return total, files
                try:
                    total += (dirpath / name).stat().st_size
                except OSError:
                    continue
            # prune obvious junk
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower()
                not in {"$recycle.bin", "system volume information", ".git"}
            ]
    except AttributeError:
        # fallback if walk unavailable
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            files += 1
            if files > _DIR_SIZE_FILE_CAP:
                break
            try:
                total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total, files


def _pg_database_size(engine: Engine) -> dict:
    out = {"ok": False, "bytes": 0, "error": None}
    try:
        with engine.connect() as conn:
            bytes_ = int(conn.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
        out["ok"] = True
        out["bytes"] = bytes_
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out


def _empty_path(error: str = "未配置") -> dict:
    return {
        "path": "",
        "paths": [],
        "exists": False,
        "total": 0,
        "used": 0,
        "free": 0,
        "used_pct": None,
        "dir_bytes": None,
        "dir_files": None,
        "error": error,
    }


def _decorate_path(item: dict) -> dict:
    item["total_label"] = _fmt_bytes(item["total"]) if item.get("total") else "—"
    item["used_label"] = _fmt_bytes(item["used"]) if item.get("used") else "—"
    item["free_label"] = _fmt_bytes(item["free"]) if item.get("free") else "—"
    db = item.get("dir_bytes")
    item["dir_label"] = _fmt_bytes(db) if db is not None else "—"
    if "paths" not in item:
        item["paths"] = [item["path"]] if item.get("path") else []
    return item


def _merge_image_paths(mold: Path, appearance: Path) -> dict:
    """注塑 + 外观合并为一张容量卡：本目录合计 + 所在磁盘。"""
    parts: list[tuple[str, Path]] = []
    if str(mold):
        parts.append(("注塑", mold))
    if str(appearance):
        parts.append(("外观", appearance))
    if not parts:
        return _empty_path("未配置图片目录")

    infos = []
    for label, path in parts:
        info = _disk_usage_info(path)
        info["label"] = label
        infos.append(info)

    existing = [i for i in infos if i.get("exists")]
    if not existing:
        merged = dict(infos[0])
        merged["path"] = " · ".join(i.get("path") or "" for i in infos if i.get("path"))
        merged["paths"] = [i["path"] for i in infos if i.get("path")]
        errs = [f"{i.get('label')}:{i.get('error')}" for i in infos if i.get("error")]
        merged["error"] = "；".join(errs) if errs else "目录不存在"
        return merged

    # 磁盘：优先用已存在路径；若多盘则取已用比例最高的那块盘作告警参考
    disk_src = max(existing, key=lambda i: float(i.get("used_pct") or 0))
    dir_bytes = sum(int(i.get("dir_bytes") or 0) for i in existing)
    dir_files = sum(int(i.get("dir_files") or 0) for i in existing)
    path_lines = []
    for i in infos:
        tag = i.get("label") or ""
        p = i.get("path") or ""
        if not p:
            continue
        size = i.get("dir_label") or _fmt_bytes(i.get("dir_bytes") or 0)
        if i.get("exists"):
            path_lines.append(f"{tag} {p}（{size}）")
        else:
            path_lines.append(f"{tag} {p}（不可用）")

    return {
        "path": "\n".join(path_lines),
        "paths": [i["path"] for i in infos if i.get("path")],
        "exists": True,
        "total": int(disk_src.get("total") or 0),
        "used": int(disk_src.get("used") or 0),
        "free": int(disk_src.get("free") or 0),
        "used_pct": disk_src.get("used_pct"),
        "dir_bytes": dir_bytes,
        "dir_files": dir_files,
        "error": None,
        "details": [
            {
                "label": i.get("label"),
                "path": i.get("path"),
                "dir_bytes": i.get("dir_bytes"),
                "dir_files": i.get("dir_files"),
                "exists": i.get("exists"),
                "error": i.get("error"),
            }
            for i in infos
        ],
    }


def capacity_snapshot() -> dict:
    stores.refresh_pg_engines()
    insp = load_inspection_settings()
    raw_csv = settings.raw_csv_dir
    meta_dir = settings.sqlite_file.parent
    mold = Path(insp.get("mold_root_path") or "")
    appearance = Path(insp.get("appearance_root_path") or "")

    paths = {
        "raw_csv": _decorate_path(_disk_usage_info(raw_csv)),
        "meta": _decorate_path(_disk_usage_info(meta_dir)),
        "images": _decorate_path(_merge_image_paths(mold, appearance)),
    }

    databases = {
        "raw": _pg_database_size(stores.raw_engine),
        "dwh": _pg_database_size(stores.dwh_engine),
        "defect": _pg_database_size(stores.defect_engine),
    }
    for item in databases.values():
        item["label"] = _fmt_bytes(item["bytes"]) if item.get("ok") else "—"

    return {"paths": paths, "databases": databases}


def _list_user_tables(engine: Engine) -> list[str]:
    try:
        return sorted(inspect(engine).get_table_names())
    except Exception:
        logger.exception("list tables failed")
        return []


def _table_columns(engine: Engine, table: str) -> list[str]:
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    except Exception:
        return []


def _pick_time_column(columns: list[str], preferred: tuple[str, ...] | None = None) -> str | None:
    order = preferred or _TIME_CANDIDATES
    lower = {c.lower(): c for c in columns}
    for name in order:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _delete_old_rows(
    engine: Engine,
    table: str,
    time_col: str,
    days: int,
) -> dict:
    tbl = ident(table)
    col = ident(time_col)
    deleted = 0
    batches = 0
    sql = text(
        f"""
        WITH doomed AS (
            SELECT ctid FROM {q(tbl)}
            WHERE {q(col)} IS NOT NULL
              AND {q(col)} < (now() - (:days) * INTERVAL '1 day')
            LIMIT {_BATCH}
        )
        DELETE FROM {q(tbl)} t
        USING doomed
        WHERE t.ctid = doomed.ctid
        """
    )
    try:
        with engine.begin() as conn:
            for _ in range(_MAX_BATCHES_PER_TABLE):
                result = conn.execute(sql, {"days": int(days)})
                n = int(result.rowcount or 0)
                deleted += n
                batches += 1
                if n < _BATCH:
                    break
        return {
            "table": tbl,
            "time_column": col,
            "deleted": deleted,
            "batches": batches,
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("cleanup table %s failed", table)
        return {
            "table": tbl,
            "time_column": col,
            "deleted": deleted,
            "batches": batches,
            "ok": False,
            "error": str(exc)[:200],
        }


def _cleanup_engine(
    engine: Engine,
    *,
    label: str,
    days: int,
    preferred_time: tuple[str, ...] | None = None,
) -> dict:
    tables = _list_user_tables(engine)
    details: list[dict] = []
    skipped: list[str] = []
    total_deleted = 0
    for table in tables:
        cols = _table_columns(engine, table)
        time_col = _pick_time_column(cols, preferred_time)
        if not time_col:
            skipped.append(table)
            continue
        item = _delete_old_rows(engine, table, time_col, days)
        details.append(item)
        if item.get("ok"):
            total_deleted += int(item.get("deleted") or 0)
    return {
        "target": label,
        "tables": len(tables),
        "cleaned": len(details),
        "skipped": skipped,
        "deleted_rows": total_deleted,
        "details": details,
    }


def _resolve_under_root(root: Path, path: Path) -> Path | None:
    try:
        root_r = root.resolve()
        path_r = path.resolve()
    except OSError:
        return None
    try:
        path_r.relative_to(root_r)
    except ValueError:
        return None
    return path_r


def _cleanup_image_root(root_str: str, days: int) -> dict:
    root_raw = str(root_str or "").strip()
    out = {
        "path": root_raw,
        "deleted_files": 0,
        "deleted_dirs": 0,
        "ok": True,
        "error": None,
        "skipped": False,
    }
    if not root_raw:
        out["skipped"] = True
        out["error"] = "未配置"
        return out
    root = Path(root_raw)
    if not root.is_dir():
        out["ok"] = False
        out["error"] = "目录不存在"
        return out
    cutoff = datetime.now() - timedelta(days=int(days))
    cutoff_ts = cutoff.timestamp()
    deleted_files = 0
    try:
        for dirpath, dirnames, filenames in root.walk(on_error=lambda _e: None):
            base = Path(dirpath)
            if _resolve_under_root(root, base) is None:
                dirnames.clear()
                continue
            for name in filenames:
                fp = base / name
                if _resolve_under_root(root, fp) is None:
                    continue
                try:
                    if fp.stat().st_mtime < cutoff_ts:
                        fp.unlink(missing_ok=True)
                        deleted_files += 1
                except OSError:
                    continue
        # remove empty dirs bottom-up
        deleted_dirs = 0
        all_dirs = sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for d in all_dirs:
            if _resolve_under_root(root, d) is None:
                continue
            try:
                next(d.iterdir())
            except StopIteration:
                try:
                    d.rmdir()
                    deleted_dirs += 1
                except OSError:
                    pass
            except OSError:
                continue
        out["deleted_files"] = deleted_files
        out["deleted_dirs"] = deleted_dirs
    except AttributeError:
        # Path.walk fallback
        for fp in list(root.rglob("*")):
            if not fp.is_file():
                continue
            if _resolve_under_root(root, fp) is None:
                continue
            try:
                if fp.stat().st_mtime < cutoff_ts:
                    fp.unlink(missing_ok=True)
                    deleted_files += 1
            except OSError:
                continue
        out["deleted_files"] = deleted_files
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)[:200]
        out["deleted_files"] = deleted_files
    return out


def run_cleanup() -> dict:
    """Worker：执行 Postgres + 图片清理，并写回 last_run_*。"""
    config = load_disk_cleanup_config()
    db_days = int(config["db_retention_days"])
    img_days = int(config["image_retention_days"])
    stores.refresh_pg_engines()

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = _cleanup_engine(
        stores.raw_engine,
        label="raw",
        days=db_days,
        preferred_time=("ingested_at", "ServerTime", "created_at"),
    )
    dwh = _cleanup_engine(
        stores.dwh_engine,
        label="dwh",
        days=db_days,
        preferred_time=("hour", "ServerTime", "ingested_at", "etl_at", "created_at"),
    )
    defect = _cleanup_engine(
        stores.defect_engine,
        label="defect",
        days=db_days,
        preferred_time=("created_at", "ingested_at", "ServerTime", "hour"),
    )

    insp = load_inspection_settings()
    images = {
        "mold": _cleanup_image_root(insp.get("mold_root_path") or "", img_days),
        "appearance": _cleanup_image_root(
            insp.get("appearance_root_path") or "", img_days
        ),
    }

    deleted_rows = (
        int(raw.get("deleted_rows") or 0)
        + int(dwh.get("deleted_rows") or 0)
        + int(defect.get("deleted_rows") or 0)
    )
    deleted_files = int(images["mold"].get("deleted_files") or 0) + int(
        images["appearance"].get("deleted_files") or 0
    )
    errors = []
    for block in (raw, dwh, defect):
        for detail in block.get("details") or []:
            if not detail.get("ok") and detail.get("error"):
                errors.append(f"{block['target']}.{detail['table']}: {detail['error']}")
    for key, block in images.items():
        if not block.get("ok") and block.get("error") and not block.get("skipped"):
            errors.append(f"images.{key}: {block['error']}")

    ok = not errors
    message = (
        f"删除库行 {deleted_rows}，图片文件 {deleted_files}"
        if ok
        else f"部分失败：{errors[0]}"
    )[:500]
    result = {
        "started_at": started,
        "db_retention_days": db_days,
        "image_retention_days": img_days,
        "raw": raw,
        "dwh": dwh,
        "defect": defect,
        "images": images,
        "deleted_rows": deleted_rows,
        "deleted_files": deleted_files,
        "errors": errors[:20],
    }
    patch_disk_cleanup_config(
        {
            "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_run_status": "success" if ok else "failed",
            "last_run_message": message,
            "last_run_result": result,
        }
    )
    return {"ok": ok, "message": message, **result}


def status_payload() -> dict:
    config = load_disk_cleanup_config()
    return {
        "config": {
            "enabled": config["enabled"],
            "db_retention_days": config["db_retention_days"],
            "image_retention_days": config["image_retention_days"],
            "run_hour": config["run_hour"],
            "last_run_time": config["last_run_time"],
            "last_run_status": config["last_run_status"],
            "last_run_message": config["last_run_message"],
            "last_run_result": config["last_run_result"],
        },
        "capacity": capacity_snapshot(),
    }
