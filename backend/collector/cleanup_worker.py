"""
LimAnalysis 磁盘清理 Worker（独立进程）。

启动：
  cd backend
  python -m collector.cleanup_worker

职责：
  - 每天按配置小时投递 disk_cleanup
  - 只消费 disk_cleanup，不抢采集/清洗任务
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.log_setup import setup_logging

setup_logging()
logger = logging.getLogger("collector.cleanup_worker")
_scheduler: BackgroundScheduler | None = None


def _tick_disk_cleanup() -> None:
    """每天定点投递磁盘清理（实际清理在本 Worker）。"""
    from app.core.disk_cleanup import (
        load_disk_cleanup_config,
        patch_disk_cleanup_config,
        request_disk_cleanup,
    )
    from collector.jobs import JOB_DISK_CLEANUP, find_active_job

    config = load_disk_cleanup_config()
    if not config.get("enabled"):
        return
    if find_active_job(JOB_DISK_CLEANUP):
        return
    now = datetime.now()
    run_hour = int(config.get("run_hour") or 3)
    if now.hour != run_hour:
        return
    today = now.strftime("%Y-%m-%d")
    last = str(config.get("last_run_time") or "")
    if last.startswith(today):
        return

    logger.info("定时投递磁盘清理任务")
    result = request_disk_cleanup(trigger="auto")
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    if result.get("accepted"):
        patch_disk_cleanup_config(
            {
                "last_run_time": stamp,
                "last_run_status": "queued",
                "last_run_message": result.get("message")
                or f"job #{result.get('job_id')}",
            }
        )
    else:
        patch_disk_cleanup_config(
            {
                "last_run_time": stamp,
                "last_run_status": "busy",
                "last_run_message": result.get("message") or "已有任务在跑",
            }
        )
    logger.info("enqueue disk_cleanup: %s", result.get("message"))


def start_cleanup_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # 每小时整点检查一次是否到了配置的 run_hour（配置变更无需重载调度器）
    _scheduler.add_job(
        _tick_disk_cleanup,
        CronTrigger(minute=0, timezone="Asia/Shanghai"),
        id="disk_cleanup_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("清理调度器已启动（按配置小时投递 disk_cleanup）")


def _handle(job: dict) -> None:
    from collector.jobs import (
        JOB_DISK_CLEANUP,
        STATUS_FAILED,
        STATUS_SUCCESS,
        finish_job,
    )

    job_id = int(job["id"])
    payload = job.get("payload") or {}
    try:
        if job.get("job_type") != JOB_DISK_CLEANUP:
            finish_job(
                job_id,
                status=STATUS_FAILED,
                message=f"unknown job_type: {job.get('job_type')}",
            )
            return

        from app.core.disk_cleanup import patch_disk_cleanup_config, run_cleanup
        from app.core.disk_cleanup_logs import (
            create_disk_cleanup_log,
            finish_disk_cleanup_log,
        )

        trigger = str(payload.get("trigger") or "manual")
        log_id = create_disk_cleanup_log(
            trigger=trigger,
            job_id=job_id,
            message="清理进行中",
        )
        t0 = time.time()
        try:
            result = run_cleanup()
        except Exception as exc:
            msg = str(exc)[:500]
            patch_disk_cleanup_config(
                {
                    "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_run_status": "failed",
                    "last_run_message": msg,
                }
            )
            finish_disk_cleanup_log(
                log_id,
                status="failed",
                message=msg,
                duration=round(time.time() - t0, 3),
                detail={"error": msg},
            )
            raise
        ok = bool(result.get("ok", True))
        msg = str(result.get("message") or "disk cleanup done")[:500]
        detail = {
            k: result.get(k)
            for k in (
                "deleted_rows",
                "deleted_files",
                "db_retention_days",
                "image_retention_days",
                "meta_prune",
                "errors",
                "raw_ok",
                "dwh_ok",
                "defect_ok",
                "images_mold_files",
                "images_appearance_files",
            )
            if k in result
        }
        finish_disk_cleanup_log(
            log_id,
            status="success" if ok else "failed",
            message=msg,
            deleted_rows=int(result.get("deleted_rows") or 0),
            deleted_files=int(result.get("deleted_files") or 0),
            duration=round(time.time() - t0, 3),
            detail=detail,
        )
        finish_job(
            job_id,
            status=STATUS_SUCCESS if ok else STATUS_FAILED,
            message=msg,
            result=result,
        )
        logger.info(
            "job #%s disk_cleanup ok=%s rows=%s files=%s",
            job_id,
            ok,
            result.get("deleted_rows"),
            result.get("deleted_files"),
        )
    except Exception as exc:
        logger.exception("job #%s failed", job_id)
        finish_job(
            job_id,
            status=STATUS_FAILED,
            message=str(exc)[:500],
            result={"error": str(exc)[:500]},
        )


def run_loop(*, poll_seconds: float = 1.0) -> None:
    from app.core import db as stores
    from app.core.meta_init import init_meta_store
    from collector.jobs import (
        CLEANUP_WORKER_TYPES,
        claim_next_job,
        now_str,
        requeue_stale_running,
    )

    init_meta_store()
    stores.refresh_pg_engines()
    boot_at = now_str()
    n = requeue_stale_running(
        "cleanup worker restarted",
        job_types=CLEANUP_WORKER_TYPES,
        started_before=boot_at,
    )
    if n:
        logger.warning("marked %s stale running jobs as failed", n)

    start_cleanup_scheduler()
    from app.core.worker_heartbeat import touch_worker_heartbeat

    def _beat(*, force: bool = False) -> None:
        try:
            touch_worker_heartbeat("cleanup", force=force)
        except Exception:
            logger.exception("cleanup heartbeat failed")

    _beat(force=True)
    logger.info(
        "cleanup worker started (poll=%.1fs, types=%s)",
        poll_seconds,
        ",".join(CLEANUP_WORKER_TYPES),
    )

    while True:
        _beat()
        job = claim_next_job(CLEANUP_WORKER_TYPES)
        if job is None:
            time.sleep(poll_seconds)
            continue
        logger.info("claimed job #%s type=%s", job["id"], job["job_type"])
        _handle(job)
        _beat(force=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LimAnalysis disk cleanup worker")
    parser.add_argument("--poll", type=float, default=1.0, help="idle poll interval seconds")
    args = parser.parse_args(argv)
    try:
        run_loop(poll_seconds=max(0.2, float(args.poll)))
    except KeyboardInterrupt:
        logger.info("cleanup worker stopped")
        return 0
    return 0


if __name__ == "__main__":
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    raise SystemExit(main())
