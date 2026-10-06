"""
调度器状态 API
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/scheduler/status")
async def get_scheduler_status():
    """获取调度器状态"""
    try:
        from backend.core.scheduler import get_task_scheduler
        
        scheduler = get_task_scheduler()
        status = scheduler.get_status()
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                **status,
                "scheduler_thread_alive": scheduler.scheduler_thread.is_alive() if scheduler.scheduler_thread else False
            }
        }
    except Exception as e:
        return {
            "code": 1,
            "message": f"获取调度器状态失败: {str(e)}",
            "data": None
        }


@router.post("/scheduler/start")
async def start_scheduler():
    """启动调度器"""
    try:
        from backend.core.scheduler import get_task_scheduler
        
        scheduler = get_task_scheduler()
        
        if scheduler.is_running:
            return {
                "code": 0,
                "message": "调度器已在运行中",
                "data": {"is_running": True}
            }
        
        scheduler.start()
        
        return {
            "code": 0,
            "message": "调度器启动成功",
            "data": {"is_running": scheduler.is_running}
        }
    except Exception as e:
        return {
            "code": 1,
            "message": f"启动调度器失败: {str(e)}",
            "data": None
        }


@router.post("/scheduler/stop")
async def stop_scheduler():
    """停止调度器"""
    try:
        from backend.core.scheduler import get_task_scheduler
        
        scheduler = get_task_scheduler()
        
        if not scheduler.is_running:
            return {
                "code": 0,
                "message": "调度器未在运行",
                "data": {"is_running": False}
            }
        
        scheduler.stop()
        
        return {
            "code": 0,
            "message": "调度器停止成功",
            "data": {"is_running": scheduler.is_running}
        }
    except Exception as e:
        return {
            "code": 1,
            "message": f"停止调度器失败: {str(e)}",
            "data": None
        }
