"""
LimAnalysis 数据聚合 Worker（独立进程）。

启动：
  cd backend
  python -m processor.agg_worker

职责：
  - 定时投递 etl_agg（已启用模型）
  - 只消费 etl_agg，不抢采集/清洗任务
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("processor.agg_worker")
_scheduler: BackgroundScheduler | None = None


def _hour_key(value: datetime | None = None) -> str:
    return (value or datetime.now()).strftime("%Y-%m-%d %H")


def _tick_agg(*, catchup: bool = False) -> None:
    from app.core.agg_config import load_agg_config, patch_agg_config
    from collector.jobs import JOB_ETL_AGG, find_active_job
    from processor.agg_runner import request_agg

    config = load_agg_config()
    if not config.get("is_active"):
        return
    if find_active_job(JOB_ETL_AGG):
        return
    last = str(config.get("last_run_time") or "").strip()
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if _hour_key(last_dt) == _hour_key():
                return
        except ValueError:
            pass

    logger.info("定时投递聚合（整点，回算窗口按各模型配置%s）", "，补跑" if catchup else "")
    try:
        result = request_agg(trigger="auto")
    except ValueError as exc:
        patch_agg_config(
            {
                "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_run_status": "skipped",
                "last_run_message": str(exc)[:500],
            }
        )
        logger.info("agg auto skipped: %s", exc)
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if result.get("accepted"):
        patch_agg_config(
            {
                "last_run_time": now,
                "last_run_status": "queued",
                "last_run_message": result.get("message") or f"job #{result.get('job_id')}",
            }
        )
    else:
        patch_agg_config(
            {
                "last_run_time": now,
                "last_run_status": "busy",
                "last_run_message": result.get("message") or "已有任务在跑",
            }
        )
    logger.info("enqueue agg: %s", result.get("message"))


def start_agg_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        _tick_agg,
        CronTrigger(minute=0, timezone="Asia/Shanghai"),
        id="etl_agg_hourly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("聚合调度器已启动（每小时整点投递 etl_agg，回算 12 小时）")
    try:
        _tick_agg(catchup=True)
    except Exception:
        logger.exception("聚合补跑失败")


def _handle(job: dict) -> None:
    from collector.jobs import JOB_ETL_AGG, STATUS_FAILED, STATUS_SUCCESS, finish_job
    from processor.agg_logs import create_agg_log, finish_agg_log, log_line
    from processor.agg_runner import execute_agg

    job_id = int(job["id"])
    payload = job.get("payload") or {}
    trigger = str(payload.get("trigger") or "manual")
    full_refresh = bool(payload.get("full_refresh"))
    run_mode = "full" if full_refresh else "incremental"
    log_id: int | None = None
    try:
        if job.get("job_type") != JOB_ETL_AGG:
            finish_job(
                job_id,
                status=STATUS_FAILED,
                message=f"unknown job_type: {job.get('job_type')}",
            )
            return
        log_id = create_agg_log(
            trigger=trigger,
            run_mode=run_mode,
            job_id=job_id,
            message="聚合进行中",
        )
        result = execute_agg(
            project_id=payload.get("project_id"),
            model_id=payload.get("model_id"),
            all_enabled=bool(payload.get("all_enabled")),
            full_refresh=full_refresh,
            backfill_hours=payload.get("backfill_hours"),
        )
        ok = bool(result.get("ok", True))
        rows = int(result.get("total_rows") or result.get("rows") or 0)
        msg = str(
            result.get("message")
            or (f"聚合完成，写入 {rows} 行" if ok else "聚合失败")
        )[:500]
        lines = list(result.get("execution_logs") or [])
        projects = list(result.get("projects") or [])
        if not projects and result.get("project_id"):
            projects = [
                {
                    "project_id": result.get("project_id"),
                    "target_table": result.get("target_table"),
                    "rows": rows,
                    "message": result.get("message") or msg,
                }
            ]
        finish_agg_log(
            log_id,
            status="success" if ok else "failed",
            message=msg,
            rows_affected=rows,
            duration=float(result.get("duration") or 0),
            lines=lines,
            projects=projects,
            run_mode=str(result.get("run_mode") or result.get("mode") or run_mode),
        )
        job_result = {
            k: v for k, v in result.items() if k != "execution_logs"
        }
        finish_job(
            job_id,
            status=STATUS_SUCCESS if ok else STATUS_FAILED,
            message=msg,
            result=job_result,
        )
        if trigger == "auto":
            from app.core.agg_config import patch_agg_config

            patch_agg_config(
                {
                    "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_run_status": "success" if ok else "failed",
                    "last_run_message": (
                        f"自动聚合完成，写入 {rows} 行"
                        if ok
                        else str(result.get("message") or "自动聚合失败")[:500]
                    ),
                }
            )
        logger.info(
            "job #%s etl_agg ok mode=%s rows=%s full_refresh=%s",
            job_id,
            result.get("mode") or result.get("run_mode"),
            rows,
            full_refresh,
        )
    except Exception as exc:
        logger.exception("job #%s failed", job_id)
        if log_id is not None:
            finish_agg_log(
                log_id,
                status="failed",
                message=str(exc)[:500],
                rows_affected=0,
                duration=0,
                lines=[log_line("error", str(exc)[:500])],
                run_mode=run_mode,
            )
        finish_job(
            job_id,
            status=STATUS_FAILED,
            message=str(exc)[:500],
            result={"error": str(exc)[:500]},
        )


def run_loop(*, poll_seconds: float = 1.0) -> None:
    from app.core import db as stores
    from app.core.meta_init import init_meta_store
    from collector.jobs import AGG_WORKER_TYPES, claim_next_job, now_str, requeue_stale_running

    init_meta_store()
    stores.refresh_pg_engines()
    # 只回收「早于本进程启动」的 running，避免误杀其他 agg worker 正在跑的任务。
    boot_at = now_str()
    n = requeue_stale_running(
        "agg worker restarted", job_types=AGG_WORKER_TYPES, started_before=boot_at
    )
    if n:
        logger.warning("marked %s stale running jobs as failed", n)

    start_agg_scheduler()
    from app.core.worker_heartbeat import touch_worker_heartbeat

    def _beat(*, force: bool = False) -> None:
        try:
            touch_worker_heartbeat("agg", force=force)
        except Exception:
            logger.exception("agg heartbeat failed")

    _beat(force=True)
    logger.info(
        "agg worker started (poll=%.1fs, types=%s)", poll_seconds, ",".join(AGG_WORKER_TYPES)
    )

    while True:
        _beat()
        job = claim_next_job(AGG_WORKER_TYPES)
        if job is None:
            time.sleep(poll_seconds)
            continue
        logger.info("claimed job #%s type=%s", job["id"], job["job_type"])
        _handle(job)
        _beat(force=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LimAnalysis ADS aggregation worker")
    parser.add_argument("--poll", type=float, default=1.0, help="idle poll interval seconds")
    args = parser.parse_args(argv)
    try:
        run_loop(poll_seconds=max(0.2, float(args.poll)))
    except KeyboardInterrupt:
        logger.info("agg worker stopped")
        return 0
    return 0


if __name__ == "__main__":
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    raise SystemExit(main())
