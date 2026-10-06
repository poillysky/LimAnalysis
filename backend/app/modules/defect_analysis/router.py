from app.core.response import ok
from app.modules.defect_analysis.service import get_summary
from fastapi import APIRouter

router = APIRouter(prefix="/defects", tags=["defects"])


@router.get("/summary")
def defect_summary():
    return ok(get_summary().model_dump())
