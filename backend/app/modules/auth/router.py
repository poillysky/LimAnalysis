from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.response import fail, ok
from app.core.tokens import issue_session, parse_token
from app.core.users import authenticate, get_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class RefreshBody(BaseModel):
    refreshToken: str = ""


@router.post("/login")
def login(body: LoginBody):
    try:
        user = authenticate(body.username, body.password)
    except PermissionError as exc:
        return JSONResponse(fail(str(exc)), status_code=401)
    return ok(issue_session(user))


@router.post("/refresh-token")
def refresh_token(body: RefreshBody):
    try:
        username = parse_token(body.refreshToken, "refresh")
        user = get_user(username)
        if user is None or not user.get("enabled"):
            raise PermissionError("账号不可用")
    except PermissionError as exc:
        return JSONResponse(fail(str(exc)), status_code=401)
    return ok(issue_session(user))


@router.get("/routes")
def async_routes():
    """前端菜单来自本地路由模块。动态路由预留空列表，不再走 mock。"""
    return ok([])
