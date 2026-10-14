"""system 子路由：项目与机台目录。

拆自原 system/router.py。增删改仅管理员。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_admin
from app.core.projects import (
    create_project,
    delete_project,
    get_project,
    list_appearance_view_options,
    load_machine_catalog,
    load_projects,
    load_system_defaults,
    update_project,
)
from app.core.response import fail, ok
from app.modules.system.schemas import ProjectCreate, ProjectUpdate

router = APIRouter()


@router.get("/projects")
def list_projects():
    return ok(
        {
            "defaults": load_system_defaults(),
            "projects": load_projects(),
            "machine_catalog": load_machine_catalog(),
        }
    )


@router.post("/projects")
def add_project(body: ProjectCreate, _admin: dict = Depends(require_admin)):
    try:
        return ok(create_project(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/projects/{project_id}/appearance-view-options")
def appearance_view_options(project_id: str):
    """编辑项目「视角名」下拉：来自该项目聚合度量 *不良数。"""
    if get_project(project_id) is None:
        return JSONResponse(fail("项目不存在"), status_code=404)
    try:
        items = list_appearance_view_options(project_id)
    except Exception as exc:
        return JSONResponse(fail(f"读取聚合字段失败：{exc}"), status_code=500)
    return ok({"project_id": project_id, "items": items})


@router.get("/projects/{project_id}")
def read_project(project_id: str):
    item = get_project(project_id)
    if item is None:
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok(item)


@router.put("/projects/{project_id}")
def edit_project(
    project_id: str,
    body: ProjectUpdate,
    _admin: dict = Depends(require_admin),
):
    try:
        item = update_project(project_id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        return JSONResponse(
            fail(f"保存失败：{exc}"),
            status_code=503 if "locked" in str(exc).lower() else 500,
        )
    if item is None:
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok(item)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str, _admin: dict = Depends(require_admin)):
    try:
        deleted = delete_project(project_id)
    except Exception as exc:
        return JSONResponse(
            fail(f"删除失败：{exc}"),
            status_code=503 if "locked" in str(exc).lower() else 500,
        )
    if not deleted:
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok({"project_id": project_id})
