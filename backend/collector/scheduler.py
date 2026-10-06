import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.sfc_config import load_sfc_config

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _tick_sfc() -> None:
    """只投递采集任务，不在本进程执行爬虫。"""
    from collector.jobs import JOB_CRAWL, find_active_job
    from collector.runner import request_crawl

    config = load_sfc_config()
    if not config.get("is_active"):
        return
    if config.get("is_running"):
        return
    if find_active_job(JOB_CRAWL):
        return
    last = str(config.get("last_run_time") or "").strip()
    interval = int(config.get("crawl_interval") or 10)
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_dt < timedelta(minutes=interval):
                return
        except ValueError:
            pass
    logger.info("定时投递 SFC 采集任务")
    result = request_crawl(trigger="auto")
    logger.info("enqueue crawl: %s", result.get("message"))


def _tick_etl() -> None:
    """定时投递已启用模型的清洗任务。"""
    from app.core.etl_config import load_etl_config, patch_etl_config
    from collector.jobs import JOB_ETL_CLEAN, find_active_job
    from processor.runner import request_etl

    config = load_etl_config()
    if not config.get("is_active"):
        return
    if find_active_job(JOB_ETL_CLEAN):
        return
    last = str(config.get("last_run_time") or "").strip()
    interval = int(config.get("run_interval") or 30)
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_dt < timedelta(minutes=interval):
                return
        except ValueError:
            pass

    logger.info("定时投递 ETL 清洗任务")
    try:
        result = request_etl(trigger="auto")
    except ValueError as exc:
        patch_etl_config(
            {
                "last_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_run_status": "skipped",
                "last_run_message": str(exc)[:500],
            }
        )
        logger.info("etl auto skipped: %s", exc)
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if result.get("accepted"):
        patch_etl_config(
            {
                "last_run_time": now,
                "last_run_status": "queued",
                "last_run_message": result.get("message") or f"job #{result.get('job_id')}",
            }
        )
    else:
        patch_etl_config(
            {
                "last_run_time": now,
                "last_run_status": "busy",
                "last_run_message": result.get("message") or "已有任务在跑",
            }
        )
    logger.info("enqueue etl: %s", result.get("message"))


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        _tick_sfc,
        IntervalTrigger(minutes=1),
        id="sfc_crawler_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _tick_etl,
        IntervalTrigger(minutes=1),
        id="etl_clean_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("调度器已启动（SFC 采集 + ETL 清洗，仅投递队列）")
