"""
SFC 爬虫服务 - FastAPI 应用入口
"""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 容器启动时初始化数据库
if os.getenv("DOCKER_ENV") == "true":
    try:
        from scripts.init_db import init_database
        init_database()
    except ImportError:
        print("⚠️ 初始化脚本未找到，跳过数据库初始化")

from app.api.v1.router import api_router
from app.core.logger import logger
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info(f"{settings.app_name} v{settings.app_version} 启动成功")
    logger.info(f"时区: {settings.tz}")
    logger.info(f"配置数据库: {settings.cfg_db_path}")
    
    # 启动定时任务调度器（包含爬虫任务和日志清理任务）
    from app.scheduler import start_scheduler
    start_scheduler()
    
    yield
    
    # 关闭时执行
    from app.scheduler import stop_scheduler
    stop_scheduler()
    logger.info(f"{settings.app_name} 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="SFC 数据爬虫服务",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
