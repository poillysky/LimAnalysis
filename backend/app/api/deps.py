"""统一鉴权依赖。

后端 131 个业务接口默认全部需要有效访问令牌；仅 /auth/login、
/auth/refresh-token 与健康检查豁免。角色强制由 require_admin 承担。

设计意图：
- 解析复用 app.core.tokens.parse_token（自研 HMAC 令牌，无第三方依赖）。
- 令牌从 Authorization 头读取，兼容前端 formatToken 的 "Bearer xxx" 前缀。
- 失败统一抛 401 + {success:false,message} 结构，与前端 http 封装约定一致。
"""

from fastapi import Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.response import fail
from app.core.tokens import parse_token
from app.core.users import get_user


class AuthError(Exception):
    """鉴权失败。由全局异常处理器转换为 401 响应。"""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# auto_error=False：缺少头时自行抛 AuthError，保证统一响应结构。
_bearer = HTTPBearer(auto_error=False)


def _extract_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not (credentials.credentials or "").strip():
        raise AuthError("缺少登录凭证")
    return credentials.credentials.strip()


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """解析访问令牌，返回当前用户。任何校验失败都抛 AuthError(401)。"""
    token = _extract_token(credentials)
    try:
        username = parse_token(token, "access")
    except PermissionError as exc:
        raise AuthError(str(exc)) from exc
    try:
        user = get_user(username)
    except Exception as exc:  # meta 库不可用时视为鉴权失败，避免裸奔
        raise AuthError("鉴权服务暂不可用", 503) from exc
    if user is None:
        raise AuthError("账号不存在")
    if not user.get("enabled"):
        raise AuthError("账号已停用")
    return user


def require_user(user: dict = Depends(current_user)) -> dict:
    """任意已登录用户。"""
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    """仅管理员。"""
    if user.get("role") != "admin":
        raise AuthError("需要管理员权限", 403)
    return user


def auth_error_response(exc: AuthError) -> JSONResponse:
    return JSONResponse(fail(exc.message), status_code=exc.status_code)
