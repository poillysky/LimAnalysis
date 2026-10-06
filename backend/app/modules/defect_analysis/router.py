from fastapi import APIRouter

from app.core.response import ok
from app.modules.defect_analysis.service import get_summary

router = APIRouter(prefix="/defects", tags=["defects"])


@router.get("/summary")
def defect_summary():
    return ok(get_summary().model_dump())
