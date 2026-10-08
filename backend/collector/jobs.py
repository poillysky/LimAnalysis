"""meta_jobs 任务队列：API 投递，Worker claim/finish。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update

from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaEtlLog, MetaJob, MetaSfcLog

logger = logging.getLogger(__name__)

# 已结束任务 / 采集日志保留：防 SQLite 与页面查询无限胀
JOB_KEEP_DAYS = 14
JOB_KEEP_MAX = 800
SFC_LOG_KEEP_DAYS = 30
SFC_LOG_KEEP_MAX = 200
RESULT_MAX_BYTES = 8_192

JOB_CRAWL = "sfc_crawl"
JOB_UPLOAD = "sfc_upload"
JOB_SYNC_SCHEMA = "sfc_sync_schema"
JOB_ETL_CLEAN = "etl_clean"
JOB_ETL_AGG = "etl_agg"
JOB_DISK_CLEANUP = "disk_cleanup"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

HEAVY_TYPES = (
    JOB_CRAWL,
    JOB_UPLOAD,
    JOB_SYNC_SCHEMA,
    JOB_ETL_CLEAN,
    JOB_DISK_CLEANUP,
)
WORKER_TYPES = HEAVY_TYPES
AGG_WORKER_TYPES = (JOB_ETL_AGG,)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_str() -> str:
    """`_now` 的公开别名。调用方要拿「进程启动时刻」当残留回收基准时用这个，
    避免跨模块 import 下划线私有名（started_at 字符串比较必须与写入时同格式）。"""
    return _now()


def enqueue_job(job_type: str, payload: dict | None = None, *, message: str = "") -> dict:
    init_meta_store()
    db = MetaSession()
    try:
        row = MetaJob(
            job_type=str(job_type),
            status=STATUS_QUEUED,
            payload=dict(payload or {}),
            message=str(message or "queued")[:500],
            result={},
            created_at=_now(),
            started_at="",
            ended_at="",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return job_to_dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_job(job_id: int) -> dict | None:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaJob, int(job_id))
        return job_to_dict(row) if row else None
    finally:
        db.close()


def job_to_dict(row: MetaJob) -> dict:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "payload": dict(row.payload or {}),
        "message": row.message or "",
        "result": dict(row.result or {}),
        "created_at": row.created_at or "",
        "started_at": row.started_at or "",
        "ended_at": row.ended_at or "",
    }


def find_active_job(job_type: str | None = None) -> dict | None:
    init_meta_store()
    db = MetaSession()
    try:
        stmt = select(MetaJob).where(
            MetaJob.status.in_((STATUS_QUEUED, STATUS_RUNNING))
        )
        if job_type:
            stmt = stmt.where(MetaJob.job_type == job_type)
        stmt = stmt.order_by(MetaJob.id.desc()).limit(1)
        row = db.scalars(stmt).first()
        return job_to_dict(row) if row else None
    finally:
        db.close()


def claim_next_job(allowed_types: tuple[str, ...] | None = None) -> dict | None:
    """领取最早一条 queued 任务并标为 running（单 Worker 串行足够）。"""
    init_meta_store()
    types = tuple(allowed_types or HEAVY_TYPES)
    db = MetaSession()
    try:
        row = db.scalars(
            select(MetaJob)
            .where(
                MetaJob.status == STATUS_QUEUED,
                MetaJob.job_type.in_(types),
            )
            .order_by(MetaJob.id.asc())
            .limit(1)
        ).first()
        if row is None:
            return None
        job_id = row.id
        started = _now()
        result = db.execute(
            update(MetaJob)
            .where(MetaJob.id == job_id, MetaJob.status == STATUS_QUEUED)
            .values(status=STATUS_RUNNING, started_at=started, message="running")
        )
        if result.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        fresh = db.get(MetaJob, job_id)
        return job_to_dict(fresh) if fresh else None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _compact_result(result: dict | None) -> dict:
    payload = dict(result or {})
    try:
        raw = json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        return {"_truncated": True, "keys": list(payload.keys())[:40]}
    if len(raw.encode("utf-8")) <= RESULT_MAX_BYTES:
        return payload
    return {
        "_truncated": True,
        "keys": list(payload.keys())[:40],
        "message": str(payload.get("message") or payload.get("error") or "")[:300],
    }


def finish_job(
    job_id: int,
    *,
    status: str,
    message: str = "",
    result: dict | None = None,
) -> dict | None:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaJob, int(job_id))
        if row is None:
            return None
        row.status = status
        row.message = str(message or "")[:500]
        row.result = _compact_result(result)
        row.ended_at = _now()
        db.commit()
        db.refresh(row)
        return job_to_dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def prune_meta_history(
    *,
    job_keep_days: int = JOB_KEEP_DAYS,
    job_keep_max: int = JOB_KEEP_MAX,
    log_keep_days: int = SFC_LOG_KEEP_DAYS,
    log_keep_max: int = SFC_LOG_KEEP_MAX,
) -> dict:
    """清理已结束的 meta_jobs / sfc·etl 运行日志，防止 SQLite 与查询持续膨胀。"""
    init_meta_store()
    job_cutoff = (datetime.now() - timedelta(days=max(1, job_keep_days))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    log_cutoff = (datetime.now() - timedelta(days=max(1, log_keep_days))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    done = (STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED)
    db = MetaSession()
    deleted_jobs = 0
    deleted_logs = 0
    deleted_etl_logs = 0
    try:
        r1 = db.execute(
            delete(MetaJob).where(
                MetaJob.status.in_(done),
                MetaJob.created_at != "",
                MetaJob.created_at < job_cutoff,
            )
        )
        deleted_jobs += int(r1.rowcount or 0)

        # 再按条数封顶：保留最新 job_keep_max 条已结束任务
        keep_ids = list(
            db.scalars(
                select(MetaJob.id)
                .where(MetaJob.status.in_(done))
                .order_by(MetaJob.id.desc())
                .limit(max(50, job_keep_max))
            ).all()
        )
        if keep_ids:
            r2 = db.execute(
                delete(MetaJob).where(
                    MetaJob.status.in_(done),
                    MetaJob.id.not_in(keep_ids),
                )
            )
            deleted_jobs += int(r2.rowcount or 0)

        r3 = db.execute(
            delete(MetaSfcLog).where(
                MetaSfcLog.status != "running",
                MetaSfcLog.started_at != "",
                MetaSfcLog.started_at < log_cutoff,
            )
        )
        deleted_logs += int(r3.rowcount or 0)

        keep_log_ids = list(
            db.scalars(
                select(MetaSfcLog.id)
                .where(MetaSfcLog.status != "running")
                .order_by(MetaSfcLog.id.desc())
                .limit(max(20, log_keep_max))
            ).all()
        )
        if keep_log_ids:
            r4 = db.execute(
                delete(MetaSfcLog).where(
                    MetaSfcLog.status != "running",
                    MetaSfcLog.id.not_in(keep_log_ids),
                )
            )
            deleted_logs += int(r4.rowcount or 0)

        r5 = db.execute(
            delete(MetaEtlLog).where(
                MetaEtlLog.status != "running",
                MetaEtlLog.started_at != "",
                MetaEtlLog.started_at < log_cutoff,
            )
        )
        deleted_etl_logs += int(r5.rowcount or 0)
        keep_etl_ids = list(
            db.scalars(
                select(MetaEtlLog.id)
                .where(MetaEtlLog.status != "running")
                .order_by(MetaEtlLog.id.desc())
                .limit(max(20, log_keep_max))
            ).all()
        )
        if keep_etl_ids:
            r6 = db.execute(
                delete(MetaEtlLog).where(
                    MetaEtlLog.status != "running",
                    MetaEtlLog.id.not_in(keep_etl_ids),
                )
            )
            deleted_etl_logs += int(r6.rowcount or 0)

        db.commit()
        if deleted_jobs or deleted_logs or deleted_etl_logs:
            logger.info(
                "pruned meta history: jobs=%s sfc_logs=%s etl_logs=%s",
                deleted_jobs,
                deleted_logs,
                deleted_etl_logs,
            )
        return {
            "deleted_jobs": deleted_jobs,
            "deleted_logs": deleted_logs,
            "deleted_etl_logs": deleted_etl_logs,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def requeue_stale_running(
    message: str = "worker restarted",
    job_types: tuple[str, ...] | None = None,
    *,
    started_before: str | None = None,
) -> int:
    """Worker 重启时回收「本进程启动之前就已在 running」的残留任务，避免永久占坑。

    ⚠️ 归属判定为什么用 started_before 而不加 worker_id 字段：
    `meta_jobs` 表没有 owner 列，而 `MetaBase.metadata.create_all()` 只会建新表、
    **不会给已存在的 SQLite 表补列**，加字段要配套手写 ALTER TABLE 迁移，
    代价远大于这个 bug 本身。

    started_before 取本进程启动时刻，于是语义正好是「我起来之前别人就在跑的任务」。
    同一 worker 崩溃重启后，它自己上一次的残留 started_at 必然早于新进程启动
    时刻 → 能被回收；而**别的 worker 此刻正在跑的任务 started_at 晚于本进程启动
    时刻** → 不会被误杀。

    调用方务必把「本进程启动时刻」传进来；不传时退化为回收全部 running
    （那是本函数的旧行为，保留只为不破坏既有调用契约，但多 worker 场景必须显式传）。
    """
    init_meta_store()
    types = tuple(job_types) if job_types else None
    db = MetaSession()
    try:
        stmt = select(MetaJob).where(MetaJob.status == STATUS_RUNNING)
        if types:
            stmt = stmt.where(MetaJob.job_type.in_(types))
        if started_before:
            # started_at 是字符串时间（见 _now 的 "%Y-%m-%d %H:%M:%S"），
            # 同一格式下字典序即时间序，可直接做字符串比较。
            # 空的 started_at 视为「时间不明但状态是 running」，一并回收 ——
            # 那必然是异常残留，正常 claim 时就会写 started_at。
            stmt = stmt.where(
                or_(MetaJob.started_at == "", MetaJob.started_at <= started_before)
            )
        rows = list(db.scalars(stmt).all())
        count = 0
        ended = _now()
        for row in rows:
            row.status = STATUS_FAILED
            row.message = message[:500]
            row.ended_at = ended
            count += 1
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
