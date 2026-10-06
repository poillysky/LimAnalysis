from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str = ""


def ok(data: Any = None, message: str = "") -> dict:
    return {"success": True, "data": data, "message": message}


def fail(message: str, data: Any = None) -> dict:
    return {"success": False, "data": data, "message": message}
