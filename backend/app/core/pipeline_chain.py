"""SFC → 清洗 → 聚合联动：成功后延迟入队下游（trigger=chain）。

挂在 collector worker 成功收尾；延迟用 collector APScheduler 的 DateTrigger，
不在 worker 循环里 sleep。调度器未起时降级为立即入队。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

_CHAIN_ETL_JOB_ID = "pipeline_chain_etl"
_CHAIN_AGG_JOB_ID = "pipeline_chain_agg"


def _delay_seconds() -> int:
    from app.core.linkage_config import load_linkage_config

    return int(load_linkage_config().get("delay_seconds") or 60)


def _linkage_enabled() -> bool:
    from app.core.linkage_config import load_linkage_config

    return bool(load_linkage_config().get("enabled"))


def _run_later(job_id: str, fn, delay_seconds: int) -> None:
    from collector.scheduler import get_scheduler

    sch = get_scheduler()
    if sch is None or not sch.running:
        logger.warning(
            "pipeline chain: scheduler not running, enqueue %s immediately",
            job_id,
        )
        try:
            fn()
        except Exception:
            logger.exception("pipeline chain immediate enqueue failed: %s", job_id)
        return

    run_at = datetime.now(sch.timezone) + timedelta(seconds=max(1, delay_seconds))
    sch.add_job(
        fn,
        DateTrigger(run_date=run_at, timezone=sch.timezone),
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "pipeline chain: scheduled %s at %s (+%ss)",
        job_id,
        run_at.isoformat(),
        delay_seconds,
    )


def _enqueue_etl_chain() -> None:
    from collector.jobs import JOB_ETL_CLEAN, find_active_job
    from processor.runner import request_etl

    if find_active_job(JOB_ETL_CLEAN):
        logger.info("pipeline chain: skip etl_clean, already active")
        return
    try:
        result = request_etl(trigger="chain")
    except ValueError as exc:
        logger.info("pipeline chain: etl_clean skipped: %s", exc)
        return
    logger.info(
        "pipeline chain: enqueue etl_clean accepted=%s %s",
        result.get("accepted"),
        result.get("message"),
    )


def _enqueue_agg_chain() -> None:
    from collector.jobs import JOB_ETL_AGG, find_active_job
    from processor.agg_runner import request_agg

    if find_active_job(JOB_ETL_AGG):
        logger.info("pipeline chain: skip etl_agg, already active")
        return
    try:
        result = request_agg(trigger="chain")
    except ValueError as exc:
        logger.info("pipeline chain: etl_agg skipped: %s", exc)
        return
    logger.info(
        "pipeline chain: enqueue etl_agg accepted=%s %s",
        result.get("accepted"),
        result.get("message"),
    )


def schedule_after_sfc_success() -> None:
    """SFC crawl/upload 成功后：延迟投递全量已启用模型清洗。"""
    if not _linkage_enabled():
        return
    _run_later(_CHAIN_ETL_JOB_ID, _enqueue_etl_chain, _delay_seconds())


def schedule_after_etl_success() -> None:
    """清洗成功后：延迟投递聚合。"""
    if not _linkage_enabled():
        return
    _run_later(_CHAIN_AGG_JOB_ID, _enqueue_agg_chain, _delay_seconds())
