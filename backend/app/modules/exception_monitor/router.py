from app.core.response import ok
from app.modules.exception_monitor.service import list_exceptions
from fastapi import APIRouter

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


@router.get("")
def exception_list():
    return ok([item.model_dump() for item in list_exceptions()])
