"""磁盘清理运行日志：写入 meta_disk_cleanup_logs。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaDiskCleanupLog


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_disk_cleanup_log(
    *,
    trigger: str = "manual",
    job_id: int = 0,
    message: str = "清理进行中",
) -> int:
    init_meta_store()
    db = MetaSession()
    try:
        row = MetaDiskCleanupLog(
            started_at=_now(),
            ended_at="",
            trigger=str(trigger or "manual")[:20],
            status="running",
            message=str(message or "清理进行中")[:500],
            deleted_rows=0,
            deleted_files=0,
            duration=0.0,
            job_id=int(job_id or 0),
            detail={},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def finish_disk_cleanup_log(
    log_id: int,
    *,
    status: str,
    message: str = "",
    deleted_rows: int = 0,
    deleted_files: int = 0,
    duration: float = 0.0,
    detail: dict | None = None,
) -> None:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaDiskCleanupLog, int(log_id))
        if row is None:
            return
        row.status = str(status or "failed")[:20]
        row.message = str(message or "")[:500]
        row.ended_at = _now()
        row.deleted_rows = int(deleted_rows or 0)
        row.deleted_files = int(deleted_files or 0)
        row.duration = float(duration or 0.0)
        if detail is not None:
            row.detail = dict(detail)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_disk_cleanup_logs(limit: int = 50) -> list[dict]:
    init_meta_store()
    db = MetaSession()
    try:
        rows = db.scalars(
            select(MetaDiskCleanupLog)
            .order_by(MetaDiskCleanupLog.id.desc())
            .limit(max(1, min(200, int(limit or 50))))
        ).all()
        return [
            {
                "id": row.id,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "trigger": row.trigger,
                "status": row.status,
                "message": row.message,
                "deleted_rows": row.deleted_rows,
                "deleted_files": row.deleted_files,
                "duration": row.duration,
                "job_id": row.job_id,
                "detail": row.detail or {},
            }
            for row in rows
        ]
    finally:
        db.close()


def clear_disk_cleanup_logs() -> dict:
    """清除已结束日志；进行中的保留。"""
    init_meta_store()
    db = MetaSession()
    try:
        result = db.execute(
            delete(MetaDiskCleanupLog).where(MetaDiskCleanupLog.status != "running")
        )
        db.commit()
        return {"deleted": int(result.rowcount or 0)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
