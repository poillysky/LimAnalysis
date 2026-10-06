"""
ETL 日志 API
"""
from fastapi import APIRouter
from backend.core.logger import get_etl_logger

router = APIRouter()


@router.get("/logs")
async def get_etl_logs(limit: int = 50):
    """
    获取 ETL 执行日志
    
    Args:
        limit: 返回日志数量限制
    """
    try:
        logger = get_etl_logger()
        logs = logger.read_etl_logs(limit=limit)
        
        # 转换为前端需要的格式
        result = []
        for idx, log in enumerate(logs):
            result.append({
                "id": idx + 1,  # 使用索引作为临时 ID
                "created_at": log.get("timestamp"),
                "model_name": log.get("model_name"),
                "model_type": log.get("model_type"),
                "status": log.get("status"),
                "trigger_type": log.get("trigger_type", "manual"),  # 触发类型
                "run_mode": log.get("run_mode", "incremental"),  # 运行模式：full 或 incremental
                "duration": log.get("duration"),
                "message": log.get("message"),
                "rows_affected": log.get("rows_affected"),
                "execution_logs": log.get("execution_logs", [])
            })
        
        return {
            "code": 0,
            "message": "success",
            "data": result
        }
    except Exception as e:
        return {
            "code": 1,
            "message": f"获取日志失败: {str(e)}",
            "data": []
        }


@router.delete("/logs/{log_id}")
async def delete_etl_log(log_id: int):
    """
    删除 ETL 执行日志
    
    Args:
        log_id: 日志 ID（基于索引）
    """
    try:
        # 注意：由于日志是 JSONL 文件，删除操作需要重写整个文件
        # 这里暂时返回成功，实际删除功能需要实现文件重写逻辑
        return {
            "code": 0,
            "message": "删除成功（注意：JSONL 文件删除功能待实现）",
            "data": None
        }
    except Exception as e:
        return {
            "code": 1,
            "message": f"删除日志失败: {str(e)}",
            "data": None
        }
