"""
API v1 路由汇总
"""
from fastapi import APIRouter

from app.api.v1 import sfc_crawler

api_router = APIRouter()

# SFC 爬虫路由
api_router.include_router(sfc_crawler.router, prefix="/sfc-crawler", tags=["SFC 爬虫"])
