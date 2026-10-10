"""数据聚合运行日志：写入 meta_agg_logs，供页面「运行日志」展示。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaAggLog


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_agg_log(
    *,
    trigger: str = "manual",
    run_mode: str = "incremental",
    job_id: int = 0,
    message: str = "聚合进行中",
) -> int:
    init_meta_store()
    db = MetaSession()
    try:
        row = MetaAggLog(
            started_at=_now(),
            ended_at="",
            trigger=str(trigger or "manual")[:20],
            run_mode=str(run_mode or "incremental")[:20],
            status="running",
            message=str(message or "聚合进行中")[:500],
            rows_affected=0,
            duration=0.0,
            job_id=int(job_id or 0),
            detail={"lines": [], "projects": []},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def finish_agg_log(
    log_id: int,
    *,
    status: str,
    message: str = "",
    rows_affected: int = 0,
    duration: float = 0.0,
    lines: list[dict] | None = None,
    projects: list[dict] | None = None,
    run_mode: str | None = None,
) -> None:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaAggLog, int(log_id))
        if row is None:
            return
        row.status = str(status or "failed")[:20]
        row.message = str(message or "")[:500]
        row.ended_at = _now()
        row.rows_affected = int(rows_affected or 0)
        row.duration = float(duration or 0.0)
        if run_mode:
            row.run_mode = str(run_mode)[:20]
        detail = dict(row.detail or {})
        if lines is not None:
            detail["lines"] = list(lines)[:200]
        if projects is not None:
            detail["projects"] = list(projects)[:50]
        row.detail = detail
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_agg_logs(limit: int = 50) -> list[dict]:
    init_meta_store()
    db = MetaSession()
    try:
        rows = db.scalars(
            select(MetaAggLog)
            .order_by(MetaAggLog.id.desc())
            .limit(max(1, min(200, int(limit or 50))))
        ).all()
        return [
            {
                "id": row.id,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "trigger": row.trigger,
                "run_mode": row.run_mode,
                "status": row.status,
                "message": row.message,
                "rows_affected": row.rows_affected,
                "duration": row.duration,
                "job_id": row.job_id,
                "detail": row.detail or {},
            }
            for row in rows
        ]
    finally:
        db.close()


def clear_agg_logs() -> dict:
    """清除已结束日志；进行中的保留。"""
    init_meta_store()
    db = MetaSession()
    try:
        result = db.execute(
            delete(MetaAggLog).where(MetaAggLog.status != "running")
        )
        db.commit()
        return {"deleted": int(result.rowcount or 0)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def log_line(level: str, message: str) -> dict:
    return {
        "time": _now(),
        "level": str(level or "info")[:20],
        "message": str(message or "")[:500],
    }
