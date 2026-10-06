from contextlib import asynccontextmanager

from app.api.router import api_router
from app.core import db as stores
from app.core.config import settings
from app.core.meta_init import init_meta_store
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # API 只服务请求；重任务调度与执行在独立 Worker（python -m collector.worker）
    init_meta_store()
    stores.refresh_pg_engines()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/api/health")
    def health():
        # 只探 meta，避免健康检查去打外部 PG 把接口拖慢
        meta = stores.ping_engine(stores.meta_engine)
        return {
            "success": True,
            "data": {
                "status": "ok" if meta["ok"] else "degraded",
                "stores": {"meta": meta},
            },
            "message": "",
        }

    return app


app = create_app()
