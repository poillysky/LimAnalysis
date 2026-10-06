"""
统一响应格式
"""
from typing import Any


def ok(data: Any = None) -> dict[str, Any]:
    """成功响应"""
    return {"code": 0, "message": "success", "data": data}


def fail(message: str, code: int = 500) -> dict[str, Any]:
    """失败响应"""
    return {"code": code, "message": message, "data": None}


def paginated(items: list, total: int, page: int, size: int) -> dict[str, Any]:
    """分页响应"""
    return ok({
        "total": total,
        "page": page,
        "size": size,
        "items": items
    })
