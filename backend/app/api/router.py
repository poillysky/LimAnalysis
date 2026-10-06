from fastapi import APIRouter

from app.core.config import settings
from app.modules.agg.router import router as agg_router
from app.modules.ai.router import router as ai_router
from app.modules.auth.router import router as auth_router
from app.modules.defect_analysis.router import router as defect_router
from app.modules.etl.router import router as etl_router
from app.modules.exception_monitor.router import router as exception_router
from app.modules.inspection.router import router as inspection_router
from app.modules.scan.router import router as scan_router
from app.modules.sfc.router import router as sfc_router
from app.modules.system.router import router as system_router

api_router = APIRouter(prefix=settings.api_prefix)
api_router.include_router(auth_router)
api_router.include_router(system_router)
api_router.include_router(sfc_router)
api_router.include_router(etl_router)
api_router.include_router(agg_router)
api_router.include_router(ai_router)
api_router.include_router(exception_router)
api_router.include_router(defect_router)
api_router.include_router(inspection_router)
api_router.include_router(scan_router)
