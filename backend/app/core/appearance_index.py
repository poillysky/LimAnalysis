"""自动外观 SN → 路径索引（meta SQLite）。

按「测试机 × 日期 × 视角」目录增量维护；注塑机维 / 扫码查图走索引，
避免每次对 5–6 台外观机重复 iterdir。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import Float, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import MetaSession, meta_engine
from app.core.meta_models import MetaBase

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
# 目录 mtime 在部分 NAS 上不可靠，辅以 TTL 强制重扫
DIR_INDEX_TTL_SEC = 120.0
SN_QUERY_CHUNK = 400

_lock = threading.RLock()
_ensured_schema = False


class AppearanceDirIndex(MetaBase):
    """每个视角目录的指纹，用于增量刷新。"""

    __tablename__ = "appearance_dir_index"
    __table_args__ = (
        UniqueConstraint(
            "project_key",
            "tester",
            "date_ymd",
            "view",
            name="uq_appearance_dir_index",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tester: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    date_ymd: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    view: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    dir_mtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class AppearanceFileIndex(MetaBase):
    """单张外观截图：文件名解析出的 SN + 路径元数据。"""

    __tablename__ = "appearance_file_index"
    __table_args__ = (
        UniqueConstraint(
            "project_key",
            "rel_path",
            name="uq_appearance_file_index_path",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sn: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    tester: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    date_ymd: Mapped[str] = mapped_column(String(8), nullable=False, default="", index=True)
    date_str: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    view: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    rel_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    mtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


def ensure_appearance_index_schema() -> None:
    global _ensured_schema
    if _ensured_schema:
        return
    with _lock:
        if _ensured_schema:
            return
        MetaBase.metadata.create_all(
            meta_engine,
            tables=[AppearanceDirIndex.__table__, AppearanceFileIndex.__table__],
        )
        _ensured_schema = True


def extract_sn_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    if stem.startswith("截图"):
        stem = stem[2:]
    if "_" in stem:
        return stem.rsplit("_", 1)[0].strip()
    return stem.strip()


def _needs_reindex(row: AppearanceDirIndex | None, dir_mtime: float, file_count: int) -> bool:
    if row is None:
        return True
    if abs(float(row.dir_mtime) - dir_mtime) > 1e-6:
        return True
    if int(row.file_count) != int(file_count):
        return True
    return False


def drop_view_dir_index(
    project_key: str, *, tester: str, date_ymd: str, view: str
) -> None:
    """目录已不存在时，删掉对应指纹 + 文件行。"""
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    tester_name = str(tester or "").strip()
    ymd = str(date_ymd or "").strip()
    view_name = str(view or "").strip()
    if not key or not tester_name or not ymd or not view_name:
        return
    with _lock:
        db = MetaSession()
        try:
            db.execute(
                delete(AppearanceFileIndex).where(
                    AppearanceFileIndex.project_key == key,
                    AppearanceFileIndex.tester == tester_name,
                    AppearanceFileIndex.date_ymd == ymd,
                    AppearanceFileIndex.view == view_name,
                )
            )
            db.execute(
                delete(AppearanceDirIndex).where(
                    AppearanceDirIndex.project_key == key,
                    AppearanceDirIndex.tester == tester_name,
                    AppearanceDirIndex.date_ymd == ymd,
                    AppearanceDirIndex.view == view_name,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def drop_files_by_rel_paths(project_key: str, rel_paths: list[str]) -> None:
    """单文件已删时，按相对路径剔除索引行。"""
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    paths = sorted({str(p).strip().replace("\\", "/") for p in rel_paths if str(p).strip()})
    if not key or not paths:
        return
    with _lock:
        db = MetaSession()
        try:
            for offset in range(0, len(paths), SN_QUERY_CHUNK):
                chunk = paths[offset : offset + SN_QUERY_CHUNK]
                db.execute(
                    delete(AppearanceFileIndex).where(
                        AppearanceFileIndex.project_key == key,
                        AppearanceFileIndex.rel_path.in_(chunk),
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def prune_project_index(
    project_key: str, live_windows: set[tuple[str, str, str]]
) -> int:
    """只保留磁盘上仍存在的 (tester, date_ymd, view)，其余整窗删除。"""
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    if not key:
        return 0
    with _lock:
        db = MetaSession()
        try:
            rows = db.scalars(
                select(AppearanceDirIndex).where(AppearanceDirIndex.project_key == key)
            ).all()
            stale = [
                row
                for row in rows
                if (str(row.tester), str(row.date_ymd), str(row.view)) not in live_windows
            ]
            if not stale:
                return 0
            for row in stale:
                db.execute(
                    delete(AppearanceFileIndex).where(
                        AppearanceFileIndex.project_key == key,
                        AppearanceFileIndex.tester == row.tester,
                        AppearanceFileIndex.date_ymd == row.date_ymd,
                        AppearanceFileIndex.view == row.view,
                    )
                )
                db.delete(row)
            db.commit()
            return len(stale)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def prune_windows_for_dates(
    project_key: str,
    *,
    view: str,
    date_ymds: list[str],
    live_windows: set[tuple[str, str, str]],
) -> int:
    """在给定生产日窗口内，清掉磁盘上已消失的测试机/日期/视角索引。"""
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    view_name = str(view or "").strip()
    days = [str(d).strip() for d in date_ymds if str(d).strip()]
    if not key or not view_name or not days:
        return 0
    with _lock:
        db = MetaSession()
        try:
            rows = db.scalars(
                select(AppearanceDirIndex).where(
                    AppearanceDirIndex.project_key == key,
                    AppearanceDirIndex.view == view_name,
                    AppearanceDirIndex.date_ymd.in_(days),
                )
            ).all()
            stale = [
                row
                for row in rows
                if (str(row.tester), str(row.date_ymd), str(row.view)) not in live_windows
            ]
            if not stale:
                return 0
            for row in stale:
                db.execute(
                    delete(AppearanceFileIndex).where(
                        AppearanceFileIndex.project_key == key,
                        AppearanceFileIndex.tester == row.tester,
                        AppearanceFileIndex.date_ymd == row.date_ymd,
                        AppearanceFileIndex.view == row.view,
                    )
                )
                db.delete(row)
            db.commit()
            return len(stale)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def ensure_view_dir_indexed(
    project_key: str,
    project_dir: Path,
    *,
    tester: str,
    date_ymd: str,
    date_str: str,
    view: str,
    view_dir: Path,
) -> None:
    """确保某个视角目录已写入索引；目录不在则删索引；TTL 内跳过磁盘。"""
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    tester_name = str(tester or "").strip()
    ymd = str(date_ymd or "").strip()
    view_name = str(view or "").strip()
    if not key or not tester_name or not ymd or not view_name:
        return
    if not view_dir.is_dir():
        drop_view_dir_index(
            key, tester=tester_name, date_ymd=ymd, view=view_name
        )
        return

    with _lock:
        db = MetaSession()
        try:
            row = db.scalar(
                select(AppearanceDirIndex).where(
                    AppearanceDirIndex.project_key == key,
                    AppearanceDirIndex.tester == tester_name,
                    AppearanceDirIndex.date_ymd == ymd,
                    AppearanceDirIndex.view == view_name,
                )
            )
            if row is not None and time.time() - float(row.indexed_at or 0) <= DIR_INDEX_TTL_SEC:
                return
        finally:
            db.close()

    try:
        dir_mtime = float(view_dir.stat().st_mtime)
    except OSError:
        drop_view_dir_index(
            key, tester=tester_name, date_ymd=ymd, view=view_name
        )
        return
    project_resolved = project_dir.resolve()
    file_rows: list[dict] = []
    newest = dir_mtime
    try:
        entries = list(view_dir.iterdir())
    except OSError:
        entries = []
    for image_file in entries:
        if not image_file.is_file() or image_file.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            resolved = image_file.resolve()
            rel = resolved.relative_to(project_resolved).as_posix()
            stat = resolved.stat()
        except (OSError, ValueError):
            continue
        mtime = float(stat.st_mtime)
        newest = max(newest, mtime)
        file_rows.append(
            {
                "sn": extract_sn_from_filename(image_file.name),
                "filename": image_file.name,
                "rel_path": rel,
                "mtime": mtime,
            }
        )
    file_count = len(file_rows)

    with _lock:
        db = MetaSession()
        try:
            row = db.scalar(
                select(AppearanceDirIndex).where(
                    AppearanceDirIndex.project_key == key,
                    AppearanceDirIndex.tester == tester_name,
                    AppearanceDirIndex.date_ymd == ymd,
                    AppearanceDirIndex.view == view_name,
                )
            )
            now = time.time()
            if not _needs_reindex(row, newest, file_count):
                if row is not None:
                    row.indexed_at = now
                    db.commit()
                return

            db.execute(
                delete(AppearanceFileIndex).where(
                    AppearanceFileIndex.project_key == key,
                    AppearanceFileIndex.tester == tester_name,
                    AppearanceFileIndex.date_ymd == ymd,
                    AppearanceFileIndex.view == view_name,
                )
            )
            disk_date = str(date_str or ymd)
            if file_rows:
                db.add_all(
                    [
                        AppearanceFileIndex(
                            project_key=key,
                            sn=item["sn"],
                            tester=tester_name,
                            date_ymd=ymd,
                            date_str=disk_date,
                            view=view_name,
                            filename=item["filename"],
                            rel_path=item["rel_path"],
                            mtime=item["mtime"],
                        )
                        for item in file_rows
                    ]
                )
            if row is None:
                db.add(
                    AppearanceDirIndex(
                        project_key=key,
                        tester=tester_name,
                        date_ymd=ymd,
                        view=view_name,
                        dir_mtime=newest,
                        file_count=file_count,
                        indexed_at=now,
                    )
                )
            else:
                row.dir_mtime = newest
                row.file_count = file_count
                row.indexed_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def query_files_by_sns(
    project_key: str,
    sns: set[str] | list[str],
    *,
    view: str,
    date_ymds: list[str],
) -> list[dict]:
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    view_name = str(view or "").strip()
    days = [str(d).strip() for d in date_ymds if str(d).strip()]
    sn_list = sorted({str(s).strip() for s in sns if str(s).strip()})
    if not key or not view_name or not days or not sn_list:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    db = MetaSession()
    try:
        for offset in range(0, len(sn_list), SN_QUERY_CHUNK):
            chunk = sn_list[offset : offset + SN_QUERY_CHUNK]
            rows = db.scalars(
                select(AppearanceFileIndex)
                .where(
                    AppearanceFileIndex.project_key == key,
                    AppearanceFileIndex.view == view_name,
                    AppearanceFileIndex.date_ymd.in_(days),
                    AppearanceFileIndex.sn.in_(chunk),
                )
                .order_by(AppearanceFileIndex.mtime.desc())
            ).all()
            for row in rows:
                rel = str(row.rel_path or "")
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append(
                    {
                        "sn": row.sn,
                        "tester": row.tester,
                        "date_ymd": row.date_ymd,
                        "date_str": row.date_str or row.date_ymd,
                        "view": row.view,
                        "filename": row.filename,
                        "rel_path": rel,
                        "mtime": float(row.mtime or 0),
                    }
                )
    finally:
        db.close()
    out.sort(key=lambda item: (-item["mtime"], item["filename"].lower()))
    return out


def query_files_by_needle(
    project_key: str, needle: str, *, limit: int = 80
) -> list[dict]:
    ensure_appearance_index_schema()
    key = str(project_key or "").strip()
    text = str(needle or "").strip().lower()
    if not key or not text:
        return []
    lim = max(1, int(limit))
    pattern = f"%{text}%"
    db = MetaSession()
    try:
        rows = db.scalars(
            select(AppearanceFileIndex)
            .where(
                AppearanceFileIndex.project_key == key,
                (
                    AppearanceFileIndex.filename.ilike(pattern)
                    | AppearanceFileIndex.sn.ilike(pattern)
                ),
            )
            .order_by(AppearanceFileIndex.mtime.desc())
            .limit(lim)
        ).all()
    finally:
        db.close()
    return [
        {
            "sn": row.sn,
            "tester": row.tester,
            "date_ymd": row.date_ymd,
            "date_str": row.date_str or row.date_ymd,
            "view": row.view,
            "filename": row.filename,
            "rel_path": str(row.rel_path or ""),
            "mtime": float(row.mtime or 0),
        }
        for row in rows
    ]
