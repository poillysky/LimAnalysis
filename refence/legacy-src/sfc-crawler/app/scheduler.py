"""
定时任务调度器

使用 APScheduler 替代 Celery，简化部署
"""
import logging
from datetime import datetime
from threading import Thread

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.db.engines import get_cfg_engine
from app.services.sfc_crawler_service import crawl_all_projects, should_run_crawler
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """获取调度器实例"""
    global _scheduler
    
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone='Asia/Shanghai',
            job_defaults={
                'coalesce': True,  # 合并错过的任务
                'max_instances': 1,  # 同一任务最多只有一个实例运行
                'misfire_grace_time': 60  # 错过任务的宽限时间（秒）
            }
        )
    
    return _scheduler


def _run_crawler_task():
    """
    爬虫任务包装函数
    
    在独立线程中执行，避免阻塞调度器
    """
    try:
        logger.info("=" * 60)
        logger.info("定时任务触发：SFC 数据爬虫")
        logger.info(f"触发时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)
        
        # 执行爬虫任务
        result = crawl_all_projects(manual=False)
        
        if result is None:
            logger.info("任务被跳过（未满足执行条件）")
        else:
            logger.info(f"任务执行完成: {result}")
        
    except Exception as e:
        logger.error(f"定时任务执行失败: {e}", exc_info=True)


def start_scheduler():
    """启动调度器"""
    scheduler = get_scheduler()
    
    if scheduler.running:
        logger.warning("调度器已经在运行")
        return
    
    # 添加定时任务：每分钟检查一次
    scheduler.add_job(
        func=_run_crawler_task,
        trigger=CronTrigger(minute='*'),  # 每分钟执行一次
        id='sfc_crawler_check',
        name='SFC 爬虫检查任务',
        replace_existing=True
    )
    
    # 添加日志清理任务：每天凌晨3点执行
    from app.tasks.cleanup_logs import add_cleanup_job_to_scheduler
    add_cleanup_job_to_scheduler(scheduler)
    
    # 添加内存清理任务：每小时执行一次
    from app.tasks.memory_cleanup import add_memory_cleanup_job_to_scheduler
    add_memory_cleanup_job_to_scheduler(scheduler)
    
    # 启动调度器
    scheduler.start()
    logger.info("✅ 调度器启动成功")
    logger.info("   任务1: SFC 爬虫检查任务")
    logger.info("   频率: 每分钟检查一次")
    logger.info("   任务2: 日志清理任务")
    logger.info("   频率: 每天凌晨3点执行（保留30天）")
    logger.info("   任务3: 内存清理任务")
    logger.info("   频率: 每小时执行一次")


def stop_scheduler():
    """停止调度器"""
    scheduler = get_scheduler()
    
    if not scheduler.running:
        logger.warning("调度器未运行")
        return
    
    scheduler.shutdown(wait=True)
    logger.info("✅ 调度器已停止")


def get_scheduler_status() -> dict:
    """
    获取调度器状态
    
    返回：
        {
            'running': bool,
            'jobs': [
                {
                    'id': str,
                    'name': str,
                    'next_run_time': str,
                    'trigger': str
                }
            ]
        }
    """
    scheduler = get_scheduler()
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None,
            'trigger': str(job.trigger)
        })
    
    return {
        'running': scheduler.running,
        'jobs': jobs
    }


def trigger_crawler_manually():
    """
    手动触发爬虫任务
    
    在独立线程中执行，立即返回
    """
    def _run():
        try:
            logger.info("手动触发爬虫任务")
            result = crawl_all_projects(manual=True)
            logger.info(f"手动任务执行完成: {result}")
        except Exception as e:
            logger.error(f"手动任务执行失败: {e}", exc_info=True)
    
    # 在独立线程中执行
    thread = Thread(target=_run, daemon=True)
    thread.start()
    
    logger.info("✅ 手动任务已提交到后台执行")
