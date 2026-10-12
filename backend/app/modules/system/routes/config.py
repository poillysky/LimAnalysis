"""system 子路由：车间配置、磁盘清理、系统默认值。

拆自原 system/router.py。运行配置类接口。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_admin
from app.core.disk_cleanup import (
    request_disk_cleanup,
    save_disk_cleanup_config,
    status_payload,
)
from app.core.linkage_config import load_linkage_config, save_linkage_config
from app.core.projects import load_system_defaults, save_system_defaults
from app.core.response import fail, ok
from app.core.workshop import load_workshop_config, save_workshop_config
from app.modules.system.schemas import (
    DefaultsUpdate,
    DiskCleanupUpdate,
    PipelineLinkageUpdate,
    WorkshopUpdate,
)

router = APIRouter()


@router.get("/workshop")
def workshop_get():
    return ok(load_workshop_config())


@router.put("/workshop")
def workshop_put(body: WorkshopUpdate):
    try:
        return ok(save_workshop_config(body.model_dump(exclude_unset=True)))
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/disk-cleanup")
def disk_cleanup_get():
    try:
        return ok(status_payload())
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.put("/disk-cleanup")
def disk_cleanup_put(body: DiskCleanupUpdate, _admin: dict = Depends(require_admin)):
    try:
        config = save_disk_cleanup_config(body.model_dump(exclude_unset=True))
        return ok({"config": config})
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.post("/disk-cleanup/run")
def disk_cleanup_run(_admin: dict = Depends(require_admin)):
    result = request_disk_cleanup(trigger="manual")
    if not result.get("accepted"):
        return JSONResponse(fail(result.get("message") or "无法入队"), status_code=409)
    return ok(result)


@router.get("/disk-cleanup/logs")
def disk_cleanup_logs(limit: int = 50):
    from app.core.disk_cleanup_logs import list_disk_cleanup_logs

    return ok({"logs": list_disk_cleanup_logs(limit=limit)})


@router.delete("/disk-cleanup/logs")
def disk_cleanup_logs_clear(_admin: dict = Depends(require_admin)):
    from app.core.disk_cleanup_logs import clear_disk_cleanup_logs

    return ok(clear_disk_cleanup_logs())


@router.get("/pipeline-linkage")
def pipeline_linkage_get():
    try:
        return ok(load_linkage_config())
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.put("/pipeline-linkage")
def pipeline_linkage_put(body: PipelineLinkageUpdate):
    try:
        return ok(save_linkage_config(body.model_dump(exclude_unset=True)))
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/defaults")
def get_defaults():
    return ok(load_system_defaults())


@router.put("/defaults")
def put_defaults(body: DefaultsUpdate):
    return ok(save_system_defaults(body.value))
