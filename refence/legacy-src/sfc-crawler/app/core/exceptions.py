"""
自定义异常
"""
from fastapi import HTTPException, status


class UnauthorizedException(HTTPException):
    """未认证异常"""
    
    def __init__(self, detail: str = "未认证"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(HTTPException):
    """无权限异常"""
    
    def __init__(self, detail: str = "无权限"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class NotFoundException(HTTPException):
    """资源不存在异常"""
    
    def __init__(self, detail: str = "资源不存在"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )
