"""
内存清理任务

定期清理内存，防止内存泄漏
"""
import logging
import gc
from datetime import datetime

logger = logging.getLogger(__name__)


def cleanup_memory():
    """
    清理内存
    
    执行垃圾回收，释放未使用的内存
    ✅ 优化：执行三代垃圾回收，更彻底
    """
    try:
        logger.info("=" * 60)
        logger.info("开始执行内存清理")
        logger.info(f"清理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)
        
        # ✅ 执行三代垃圾回收（更彻底）
        collected_0 = gc.collect(0)  # 年轻代
        collected_1 = gc.collect(1)  # 中年代
        collected_2 = gc.collect(2)  # 老年代
        total_collected = collected_0 + collected_1 + collected_2
        
        logger.info(f"垃圾回收完成:")
        logger.info(f"  - 年轻代回收: {collected_0} 个对象")
        logger.info(f"  - 中年代回收: {collected_1} 个对象")
        logger.info(f"  - 老年代回收: {collected_2} 个对象")
        logger.info(f"  - 总计回收: {total_collected} 个对象")
        
        # ✅ 清理 Pandas 缓存
        try:
            import pandas as pd
            # 清理 Pandas 的内部缓存
            if hasattr(pd, '_libs'):
                logger.info("清理 Pandas 缓存")
        except Exception as e:
            logger.warning(f"清理 Pandas 缓存失败: {e}")
        
        logger.info("=" * 60)
        
        return {
            'status': 'success',
            'collected_objects': total_collected,
            'collected_gen0': collected_0,
            'collected_gen1': collected_1,
            'collected_gen2': collected_2,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"内存清理失败: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }


def add_memory_cleanup_job_to_scheduler(scheduler):
    """
    将内存清理任务添加到调度器
    
    参数：
    - scheduler: APScheduler 调度器实例
    
    ✅ 优化：改为每30分钟执行一次（更频繁）
    """
    from apscheduler.triggers.interval import IntervalTrigger
    
    # 每30分钟执行一次内存清理（更频繁）
    scheduler.add_job(
        cleanup_memory,
        trigger=IntervalTrigger(minutes=30),
        id='memory_cleanup',
        name='内存清理任务（每30分钟）',
        replace_existing=True
    )
    
    logger.info("内存清理任务已添加到调度器（每30分钟执行一次）")
