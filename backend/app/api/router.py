from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.core.config import settings
from app.modules.agg.router import router as agg_router
from app.modules.ai.router import router as ai_router
from app.modules.auth.router import router as auth_router
from app.modules.defect_analysis.router import router as defect_router
from app.modules.etl.router import router as etl_router
from app.modules.exception_monitor.router import router as exception_router
from app.modules.inspection.router import media_router as inspection_media_router
from app.modules.inspection.router import router as inspection_router
from app.modules.scan.router import router as scan_router
from app.modules.sfc.router import router as sfc_router
from app.modules.system.router import router as system_router

api_router = APIRouter(prefix=settings.api_prefix)

# 鉴权豁免：auth（登录/刷新/routes）、健康检查、图片 GET（短时 ticket 自证）。
# 其余业务路由默认全量鉴权。
api_router.include_router(auth_router)
_auth_guarded = [Depends(require_user)]
api_router.include_router(system_router, dependencies=_auth_guarded)
api_router.include_router(sfc_router, dependencies=_auth_guarded)
api_router.include_router(etl_router, dependencies=_auth_guarded)
api_router.include_router(agg_router, dependencies=_auth_guarded)
api_router.include_router(ai_router, dependencies=_auth_guarded)
api_router.include_router(exception_router, dependencies=_auth_guarded)
api_router.include_router(defect_router, dependencies=_auth_guarded)
api_router.include_router(inspection_router, dependencies=_auth_guarded)
api_router.include_router(inspection_media_router)
api_router.include_router(scan_router, dependencies=_auth_guarded)
