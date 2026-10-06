"""
FastAPI 依赖项
"""
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedException
from app.core.security import decode_access_token
from app.db.engines import get_cfg_engine, get_mysql_engine


def get_cfg_db():
    """获取配置数据库会话（SQLite）"""
    engine = get_cfg_engine()
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def get_business_db(config_name: str = "default"):
    """获取业务数据库会话（MySQL）"""
    engine = get_mysql_engine(config_name)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def get_db():
    """获取数据库会话（默认使用配置数据库）"""
    yield from get_cfg_db()


def _parse_bearer_token(authorization: str) -> str:
    """解析 Bearer Token"""
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedException("认证格式错误，应为: Bearer <token>")
    return parts[1]


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    """获取当前用户（从 JWT Token）"""
    if not authorization:
        raise UnauthorizedException("未提供认证信息")
    
    # 解析 Bearer Token
    token = _parse_bearer_token(authorization)
    
    # 解码 Token
    payload = decode_access_token(token)
    if not payload:
        raise UnauthorizedException("Token 无效或已过期")
    
    # 验证必要字段
    user_id = payload.get("user_id")
    if not user_id:
        raise UnauthorizedException("Token 数据不完整")
    
    return {
        "user_id": user_id,
        "username": payload.get("username"),
        "role": payload.get("role", "user"),
    }


# 类型别名
CurrentUser = Annotated[dict, Depends(get_current_user)]
CfgDBSession = Annotated[Session, Depends(get_cfg_db)]
BusinessDBSession = Annotated[Session, Depends(get_business_db)]
DBSession = Annotated[Session, Depends(get_db)]
