from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.inspection import (
    bootstrap,
    image_response,
    list_appearance_folders,
    list_dir_entries,
    list_viewer_dates,
    list_viewer_images,
    load_settings,
    save_settings,
    search_viewer_images,
)
from app.core.response import fail, ok
from app.modules.inspection.schemas import InspectionSettingsIn

router = APIRouter(prefix="/inspection", tags=["inspection"])


@router.get("/bootstrap")
def inspection_bootstrap():
    return ok(bootstrap())


@router.get("/settings")
def inspection_settings_get():
    return ok(load_settings())


@router.put("/settings")
def inspection_settings_put(body: InspectionSettingsIn):
    return ok(save_settings(body.model_dump(exclude_unset=True)))


@router.get("/dirs")
def inspection_dirs(parent: str = ""):
    try:
        return ok(list_dir_entries(parent))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/folders")
def inspection_viewer_folders(
    project_id: str,
    tester: str = "",
    source: str = "appearance",
):
    try:
        if source != "appearance":
            raise ValueError("该接口仅用于自动外观")
        return ok(list_appearance_folders(project_id, tester))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/dates")
def inspection_viewer_dates(
    project_id: str,
    machine: str,
    source: str = "mold",
    camera: str = "",
):
    try:
        return ok(list_viewer_dates(project_id, machine, source, camera))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/images")
def inspection_viewer_images(
    project_id: str,
    machine: str,
    cavity: str,
    date: str,
    status: str = "OK",
    source: str = "mold",
):
    try:
        return ok(list_viewer_images(project_id, machine, cavity, date, status, source))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/search")
def inspection_viewer_search(
    project_id: str,
    q: str = Query(default=""),
    source: str = "mold",
):
    try:
        return ok(search_viewer_images(project_id, q, source=source))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/image")
def inspection_image(rel: str, source: str = "mold"):
    try:
        return image_response(rel, source)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
