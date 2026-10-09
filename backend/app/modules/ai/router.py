"""AI 模型连接配置。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.ai_client import list_ai_models, test_ai_connection
from app.core.ai_config import load_ai_config_public, save_ai_config
from app.core.response import fail, ok

router = APIRouter(prefix="/ai", tags=["ai"])


class AiConfigUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout_seconds: int | None = None
    temperature: float | None = None
    api_key: str | None = Field(default=None, description="不传或空=不改密钥")
    clear_api_key: bool = False


@router.get("/config")
def get_config():
    return ok(load_ai_config_public())


@router.put("/config")
def put_config(body: AiConfigUpdate):
    try:
        return ok(save_ai_config(body.model_dump(exclude_unset=True)))
    except Exception as exc:
        return JSONResponse(fail(f"保存失败: {exc}"), status_code=400)


@router.post("/test")
def post_test():
    result = test_ai_connection()
    if not result.get("ok"):
        return JSONResponse(fail(result.get("message") or "连接失败"), status_code=400)
    return ok(result)


@router.get("/models")
def get_models():
    result = list_ai_models()
    if not result.get("ok"):
        return JSONResponse(fail(result.get("error") or "拉取失败"), status_code=400)
    return ok(result)
