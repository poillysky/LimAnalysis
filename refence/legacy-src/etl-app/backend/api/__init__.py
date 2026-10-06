"""
ETL API 路由模块
"""
from fastapi import APIRouter

from backend.api import models, fields, execute, statistics, config, logs, formula_helper, scheduler

# 创建主路由
router = APIRouter()

# 注册子路由（去掉 /etl 前缀，因为 main.py 中已经有 /api/v1 前缀）
router.include_router(models.router, prefix="/etl", tags=["ETL Models"])
router.include_router(fields.router, prefix="/etl", tags=["ETL Fields"])
router.include_router(execute.router, prefix="/etl", tags=["ETL Execute"])
router.include_router(statistics.router, prefix="/etl", tags=["ETL Statistics"])
router.include_router(config.router, prefix="/etl", tags=["ETL Config"])
router.include_router(logs.router, prefix="/etl", tags=["ETL Logs"])
router.include_router(formula_helper.router, prefix="/etl", tags=["Formula Helper"])
router.include_router(scheduler.router, prefix="/etl", tags=["ETL Scheduler"])
