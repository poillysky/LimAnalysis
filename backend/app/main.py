from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core import db as stores
from app.core.config import settings
from app.core.meta_init import init_meta_store
from app.core.runtime_status import build_runtime_status


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # API 只服务请求；重任务调度与执行在独立 Worker（python -m collector.worker）
    init_meta_store()
    stores.refresh_pg_engines()
    try:
        from app.core.defect_store import ensure_defect_tables

        ensure_defect_tables()
    except Exception:
        pass
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
        """值守探测：meta + 三库 + 调度/任务摘要。"""
        try:
            data = build_runtime_status()
        except Exception as exc:
            meta = stores.ping_engine(stores.meta_engine)
            data = {
                "status": "degraded",
                "stores": {"meta": meta},
                "error": str(exc)[:300],
            }
        return {"success": True, "data": data, "message": ""}

    return app


app = create_app()
