import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import AuthError, auth_error_response
from app.api.router import api_router
from app.core import db as stores
from app.core.a2b_heartbeat import STALE_SECONDS, upsert_heartbeat
from app.core.config import settings
from app.core.log_setup import setup_logging
from app.core.meta_init import init_meta_store
from app.core.runtime_status import build_runtime_status

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # API 只服务请求；重任务调度与执行在独立 Worker（python -m collector.worker）
    setup_logging()
    init_meta_store()
    stores.refresh_pg_engines()
    try:
        from app.core.defect_store import ensure_defect_tables

        ensure_defect_tables()
    except Exception:
        logger.exception("缺陷库表初始化失败（ensure_defect_tables），相关功能可能不可用")
    yield


async def _parse_heartbeat_body(request: Request) -> dict:
    """兼容 JSON / 表单 / query。"""
    data: dict = {}
    if request.query_params:
        data.update({k: v for k, v in request.query_params.items()})
    content_type = (request.headers.get("content-type") or "").lower()
    if request.method == "POST":
        try:
            if "application/json" in content_type or not content_type:
                body = await request.json()
                if isinstance(body, dict):
                    data.update(body)
            elif (
                "application/x-www-form-urlencoded" in content_type
                or "multipart/form-data" in content_type
            ):
                form = await request.form()
                data.update({k: str(v) for k, v in form.items()})
        except Exception:
            pass
    return data


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

    @app.exception_handler(AuthError)
    async def _auth_error_handler(_request: Request, exc: AuthError):
        return auth_error_response(exc)

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

    async def receive_a2b_heartbeat(request: Request):
        """A2BCopyTray 无鉴权心跳接收（兼容 /api/heartbeat 与 /api/client/heartbeat）。"""
        data = await _parse_heartbeat_body(request)
        try:
            row = upsert_heartbeat(data)
        except Exception as exc:
            logger.exception("A2B 心跳写入失败")
            return JSONResponse(
                {
                    "success": False,
                    "error": str(exc)[:300],
                },
                status_code=500,
            )
        if row is None:
            return JSONResponse(
                {
                    "success": False,
                    "error": "缺少 clientId / deviceAlias / machine",
                    "hint": "请 POST JSON，字段含 clientId 或 machine",
                },
                status_code=400,
            )
        return {
            "success": True,
            "client_id": row["client_id"],
            "machine_name": row["machine"],
            "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timeout_seconds": STALE_SECONDS,
        }

    app.add_api_route(
        "/api/heartbeat",
        receive_a2b_heartbeat,
        methods=["GET", "POST"],
    )
    app.add_api_route(
        "/api/client/heartbeat",
        receive_a2b_heartbeat,
        methods=["GET", "POST"],
    )

    return app


app = create_app()
