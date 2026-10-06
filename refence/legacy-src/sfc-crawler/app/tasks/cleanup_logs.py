"""
日志清理任务
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_old_logs(days: int = 30) -> int:
    """
    清理超过指定天数的日志文件
    
    参数：
    - days: 保留天数（默认 30 天）
    
    返回：
    - 删除的文件数量
    """
    try:
        # 日志目录
        log_dir = Path("data/logs/sfc")
        
        if not log_dir.exists():
            logger.info("日志目录不存在，跳过清理")
            return 0
        
        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_date_str = cutoff_date.strftime('%Y%m%d')
        
        deleted_count = 0
        
        # 遍历日志文件
        for log_file in log_dir.glob("*.jsonl"):
            # 从文件名提取日期（格式：YYYYMMDD.jsonl）
            file_date_str = log_file.stem  # 去掉 .jsonl 后缀
            
            try:
                # 比较日期字符串（YYYYMMDD 格式可以直接比较）
                if file_date_str < cutoff_date_str:
                    log_file.unlink()
                    deleted_count += 1
                    logger.info(f"删除过期日志文件: {log_file.name}")
            except Exception as e:
                logger.error(f"删除日志文件失败: {log_file.name} - {e}")
        
        if deleted_count > 0:
            logger.info(f"日志清理完成，删除 {deleted_count} 个文件")
        else:
            logger.info("没有需要清理的日志文件")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"日志清理失败: {e}")
        return 0


def add_cleanup_job_to_scheduler(scheduler):
    """
    将日志清理任务添加到现有的调度器
    
    参数：
    - scheduler: APScheduler 调度器实例
    """
    from apscheduler.triggers.cron import CronTrigger
    
    # 每天凌晨3点执行清理
    scheduler.add_job(
        cleanup_old_logs,
        trigger=CronTrigger(hour=3, minute=0),
        id='cleanup_logs',
        name='清理过期日志（保留30天）',
        replace_existing=True
    )
    
    logger.info("日志清理任务已添加到调度器（每天凌晨3点执行，保留30天）")
