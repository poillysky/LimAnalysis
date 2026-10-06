"""
ETL 统计信息 API
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/statistics")
async def get_statistics():
    """获取统计信息"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "total_models": 0,
            "enabled_models": 0,
            "total_runs": 0,
            "success_rate": 0
        }
    }
