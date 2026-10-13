"""system 子路由：A2B 客户端心跳监控状态。"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.a2b_heartbeat import STALE_SECONDS, build_a2b_status
from app.core.response import fail, ok

router = APIRouter()


@router.get("/a2b-heartbeat/status")
def a2b_heartbeat_status(
    mode: str = Query(..., description="mold | appearance"),
    stale_seconds: int | None = Query(default=None, ge=10, le=3600),
):
    try:
        data = build_a2b_status(
            mode=mode,
            stale_seconds=stale_seconds if stale_seconds is not None else STALE_SECONDS,
        )
        return ok(data)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)
