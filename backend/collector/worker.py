"""
LimAnalysis 重任务 Worker（独立进程）。

启动：
  cd backend
  python -m collector.worker

职责：
  - 定时调度：只投递 sfc_crawl / disk_cleanup 到 meta_jobs
  - 串行消费：sfc_crawl / sfc_upload / sfc_sync_schema / etl_clean / disk_cleanup
  - 数据聚合 etl_agg 由独立进程 python -m processor.agg_worker 消费
主 API 进程不应再跑采集、大批量入库或清洗。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("collector.worker")


def _handle(job: dict) -> None:
    from collector.jobs import (
        JOB_CRAWL,
        JOB_DISK_CLEANUP,
        JOB_ETL_CLEAN,
        JOB_SYNC_SCHEMA,
        JOB_UPLOAD,
        STATUS_FAILED,
        STATUS_SUCCESS,
        finish_job,
    )
    from collector.runner import (
        execute_crawl,
        execute_sync_schema_file,
        execute_upload_file,
    )
    from processor.runner import execute_etl

    job_id = int(job["id"])
    job_type = job["job_type"]
    payload = job.get("payload") or {}
    try:
        if job_type == JOB_DISK_CLEANUP:
            from datetime import datetime

            from app.core.disk_cleanup import patch_disk_cleanup_config, run_cleanup

            try:
                result = run_cleanup()
            except Exception as exc:
                patch_disk_cleanup_config(
                    {
                        "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_run_status": "failed",
                        "last_run_message": str(exc)[:500],
                    }
                )
                raise
            ok = bool(result.get("ok", True))
            finish_job(
                job_id,
                status=STATUS_SUCCESS if ok else STATUS_FAILED,
                message=str(result.get("message") or "disk cleanup done")[:500],
                result=result,
            )
            logger.info(
                "job #%s disk_cleanup ok=%s rows=%s files=%s",
                job_id,
                ok,
                result.get("deleted_rows"),
                result.get("deleted_files"),
            )
            return
        if job_type == JOB_ETL_CLEAN:
            result = execute_etl(
                project_id=payload.get("project_id"),
                model_id=payload.get("model_id"),
                all_enabled=bool(payload.get("all_enabled")),
                full_refresh=bool(payload.get("full_refresh")),
            )
            ok = bool(result.get("ok", True))
            finish_job(
                job_id,
                status=STATUS_SUCCESS if ok else STATUS_FAILED,
                message="etl clean done",
                result=result,
            )
            if str(payload.get("trigger") or "") == "auto":
                from datetime import datetime

                from app.core.etl_config import patch_etl_config

                rows = result.get("total_rows") or result.get("rows") or 0
                patch_etl_config(
                    {
                        "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_run_status": "success" if ok else "failed",
                        "last_run_message": (
                            f"自动清洗完成，写入 {rows} 行"
                            if ok
                            else str(result.get("message") or "自动清洗失败")[:500]
                        ),
                    }
                )
            logger.info(
                "job #%s etl_clean ok mode=%s rows=%s full_refresh=%s",
                job_id,
                result.get("mode"),
                result.get("rows") or result.get("total_rows"),
                payload.get("full_refresh"),
            )
            return
        if job_type == JOB_CRAWL:
            trigger = str(payload.get("trigger") or "manual")
            result = execute_crawl(trigger=trigger)
            finish_job(
                job_id,
                status=STATUS_SUCCESS,
                message="crawl done",
                result=result,
            )
            logger.info("job #%s crawl ok log_id=%s", job_id, result.get("log_id"))
            return
        if job_type == JOB_UPLOAD:
            file_path = str(payload.get("file_path") or "")
            result = execute_upload_file(
                str(payload.get("project_id") or ""),
                file_path,
                str(payload.get("filename") or ""),
            )
            # 入库成功后立即删除本地 CSV（失败则保留，与爬虫行为一致）
            if file_path:
                try:
                    Path(file_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("upload csv unlink failed: %s", file_path)
            finish_job(
                job_id,
                status=STATUS_SUCCESS,
                message=f"upload {result.get('rows', 0)} rows",
                result=result,
            )
            logger.info(
                "job #%s upload ok rows=%s table=%s",
                job_id,
                result.get("rows"),
                result.get("table"),
            )
            return
        if job_type == JOB_SYNC_SCHEMA:
            result = execute_sync_schema_file(
                str(payload.get("project_id") or ""),
                str(payload.get("file_path") or ""),
            )
            finish_job(
                job_id,
                status=STATUS_SUCCESS,
                message="schema synced",
                result=result,
            )
            logger.info("job #%s sync-schema ok table=%s", job_id, result.get("table"))
            return
        finish_job(
            job_id,
            status=STATUS_FAILED,
            message=f"unknown job_type: {job_type}",
        )
    except Exception as exc:
        logger.exception("job #%s failed", job_id)
        finish_job(
            job_id,
            status=STATUS_FAILED,
            message=str(exc)[:500],
            result={"error": str(exc)[:500]},
        )


def run_loop(*, poll_seconds: float = 1.0, only: tuple[str, ...] | None = None) -> None:
    from app.core import db as stores
    from app.core.meta_init import init_meta_store
    from collector.jobs import WORKER_TYPES, claim_next_job, now_str, requeue_stale_running
    from collector.runner import clear_stale_running
    from collector.scheduler import start_scheduler

    init_meta_store()
    stores.refresh_pg_engines()
    # 先取启动时刻，再做残留回收：只有「早于本进程启动」的任务才归我们回收。
    # 少了这个基准，多 worker 并存（如 `--only crawl` 与全量 worker 同跑）时，
    # 任一 worker 重启都会把别人正在执行的任务误标为 failed。
    boot_at = now_str()
    clear_stale_running()
    n = requeue_stale_running(
        "worker restarted",
        job_types=WORKER_TYPES if only is None else only,
        started_before=boot_at,
    )
    if n:
        logger.warning("marked %s stale running jobs as failed", n)

    # 调度器只在 Worker 内启动（投递队列，不执行采集）
    start_scheduler()
    logger.info(
        "worker started (poll=%.1fs, only=%s)",
        poll_seconds,
        ",".join(only) if only else "all",
    )

    while True:
        job = claim_next_job(only or WORKER_TYPES)
        if job is None:
            time.sleep(poll_seconds)
            continue
        logger.info("claimed job #%s type=%s", job["id"], job["job_type"])
        _handle(job)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LimAnalysis SFC/raw heavy-job worker")
    parser.add_argument(
        "--poll",
        type=float,
        default=1.0,
        help="idle poll interval seconds",
    )
    parser.add_argument(
        "--only",
        choices=("crawl", "upload", "schema", "etl", "cleanup"),
        action="append",
        help="limit job types (repeatable); default all",
    )
    args = parser.parse_args(argv)

    type_map = {
        "crawl": "sfc_crawl",
        "upload": "sfc_upload",
        "schema": "sfc_sync_schema",
        "etl": "etl_clean",
        "cleanup": "disk_cleanup",
    }
    only = tuple(type_map[x] for x in (args.only or [])) or None
    try:
        run_loop(poll_seconds=max(0.2, float(args.poll)), only=only)
    except KeyboardInterrupt:
        logger.info("worker stopped")
        return 0
    return 0


if __name__ == "__main__":
    # 保证 backend 根在 path 上
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    raise SystemExit(main())
