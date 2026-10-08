"""值守用运行状态：库连通 + Worker 心跳 + 调度/任务最近状态。"""

from __future__ import annotations

from sqlalchemy import select

from app.core import db as stores
from app.core.agg_config import load_agg_config
from app.core.disk_cleanup import load_disk_cleanup_config
from app.core.etl_config import load_etl_config
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaJob
from app.core.sfc_config import load_sfc_config
from app.core.worker_heartbeat import worker_heartbeat_status
from app.core.workshop import load_workshop_config
from collector.jobs import (
    JOB_CRAWL,
    JOB_DISK_CLEANUP,
    JOB_ETL_AGG,
    JOB_ETL_CLEAN,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
)


def _latest_jobs(types: tuple[str, ...], limit: int = 1) -> list[dict]:
    init_meta_store()
    db = stores.MetaSession()
    try:
        rows = db.scalars(
            select(MetaJob)
            .where(MetaJob.job_type.in_(types))
            .order_by(MetaJob.id.desc())
            .limit(limit)
        ).all()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "job_type": row.job_type,
                    "status": row.status,
                    "message": (row.message or "")[:200],
                    "created_at": row.created_at or "",
                    "started_at": row.started_at or "",
                    "ended_at": row.ended_at or "",
                }
            )
        return out
    finally:
        db.close()


def _job_summary(job_type: str) -> dict:
    jobs = _latest_jobs((job_type,), 1)
    latest = jobs[0] if jobs else None
    active = latest is not None and latest["status"] in (
        STATUS_QUEUED,
        STATUS_RUNNING,
    )
    ok = latest is None or latest["status"] in (
        STATUS_SUCCESS,
        STATUS_QUEUED,
        STATUS_RUNNING,
    )
    return {
        "latest": latest,
        "active": active,
        "ok": ok,
    }


def build_runtime_status() -> dict:
    meta = stores.ping_engine(stores.meta_engine)
    stores.refresh_pg_engines()
    raw = stores.ping_engine(stores.raw_engine)
    dwh = stores.ping_engine(stores.dwh_engine)
    defect = stores.ping_engine(stores.defect_engine)

    workshop = load_workshop_config()
    sfc = load_sfc_config()
    etl = load_etl_config()
    agg = load_agg_config()
    cleanup = load_disk_cleanup_config()
    workers = worker_heartbeat_status()

    crawl_job = _job_summary(JOB_CRAWL)
    etl_job = _job_summary(JOB_ETL_CLEAN)
    agg_job = _job_summary(JOB_ETL_AGG)
    cleanup_job = _job_summary(JOB_DISK_CLEANUP)

    stores_ok = all(x["ok"] for x in (meta, raw, dwh, defect))
    workers_ok = all(bool(workers.get(role, {}).get("alive")) for role in ("collector", "agg"))
    if stores_ok and workers_ok:
        status = "ok"
    else:
        status = "degraded"

    return {
        "status": status,
        "workshop": workshop,
        "stores": {
            "meta": meta,
            "raw": raw,
            "dwh": dwh,
            "defect": defect,
        },
        "workers": workers,
        "schedulers": {
            "sfc": {
                "is_active": bool(sfc.get("is_active")),
                "blocked_by_workshop": bool(workshop.get("offline")),
                "last_run_time": sfc.get("last_run_time") or "",
                "last_run_status": sfc.get("last_run_status") or "",
                "job": crawl_job,
            },
            "etl": {
                "is_active": bool(etl.get("is_active")),
                "last_run_time": etl.get("last_run_time") or "",
                "last_run_status": etl.get("last_run_status") or "",
                "last_run_message": etl.get("last_run_message") or "",
                "job": etl_job,
            },
            "agg": {
                "is_active": bool(agg.get("is_active")),
                "last_run_time": agg.get("last_run_time") or "",
                "last_run_status": agg.get("last_run_status") or "",
                "last_run_message": agg.get("last_run_message") or "",
                "job": agg_job,
            },
            "disk_cleanup": {
                "enabled": bool(cleanup.get("enabled")),
                "last_run_time": cleanup.get("last_run_time") or "",
                "last_run_status": cleanup.get("last_run_status") or "",
                "last_run_message": cleanup.get("last_run_message") or "",
                "job": cleanup_job,
            },
        },
    }
