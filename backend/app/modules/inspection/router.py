from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.inspection import (
    appearance_index_status,
    bootstrap,
    image_response,
    list_appearance_folders,
    list_appearance_view_counts,
    list_dir_entries,
    list_viewer_dates,
    list_viewer_images,
    load_settings,
    save_settings,
    search_viewer_images,
    warm_appearance_index,
)
from app.core.response import fail, ok
from app.core.tokens import parse_media_ticket
from app.modules.inspection.schemas import InspectionSettingsIn

router = APIRouter(prefix="/inspection", tags=["inspection"])
# 图片 GET 不走 Bearer：<img> 无法带 Authorization，改用短时签名票据自证。
media_router = APIRouter(prefix="/inspection", tags=["inspection"])


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
    dim: str = "tester",
):
    try:
        if source != "appearance":
            raise ValueError("该接口仅用于自动外观")
        return ok(list_appearance_folders(project_id, tester, dim=dim))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/dates")
def inspection_viewer_dates(
    project_id: str,
    machine: str = "",
    source: str = "mold",
    camera: str = "",
    dim: str = "tester",
    body: str = "",
):
    """日期列表。传 body=本体号（如 A1）时按 ServerTime 生产日；否则按机台。"""
    try:
        return ok(
            list_viewer_dates(
                project_id, machine, source, camera, dim=dim, body=body
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/images")
def inspection_viewer_images(
    project_id: str,
    machine: str = "",
    cavity: str = "",
    date: str = "",
    status: str = "OK",
    source: str = "mold",
    dim: str = "tester",
    camera: str = "",
    order: str = "asc",
    body: str = "",
):
    """取图。传 body 时按本体号；否则按机台×穴位。"""
    try:
        newest_first = str(order or "asc").strip().lower() == "desc"
        return ok(
            list_viewer_images(
                project_id,
                machine,
                cavity,
                date,
                status,
                source,
                dim=dim,
                camera=camera,
                body=body,
                newest_first=newest_first,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/appearance-view-counts")
def inspection_appearance_view_counts(
    project_id: str,
    machine: str = "",
    date: str = "",
    cavity: str = "",
    dim: str = "mold",
    body: str = "",
):
    """外观各视角数量：dim=mold 按生产日（机台×穴或本体号）；dim=tester 按截图日目录。"""
    try:
        return ok(
            list_appearance_view_counts(
                project_id, machine, cavity, date, dim=dim, body=body
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/search")
def inspection_viewer_search(
    project_id: str,
    q: str = Query(default=""),
    source: str = "mold",
    dim: str = "tester",
):
    try:
        return ok(search_viewer_images(project_id, q, source=source, dim=dim))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/viewer/appearance-index")
def inspection_appearance_index(project_id: str):
    """自动外观 SN 索引状态：生成中 / 已完成 / 未生成。"""
    try:
        return ok(appearance_index_status(project_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/viewer/appearance-index/warm")
def inspection_appearance_index_warm(project_id: str):
    """进页预热：后台全量建/刷索引，之后只增量。"""
    try:
        return ok(warm_appearance_index(project_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@media_router.get("/image")
def inspection_image(rel: str, source: str = "mold", ticket: str = ""):
    """图片二进制。鉴权靠 ticket（绑定 source+rel），不读 Authorization。"""
    try:
        ticket_source, ticket_rel = parse_media_ticket(ticket)
    except PermissionError as exc:
        return JSONResponse(fail(str(exc)), status_code=401)
    if ticket_source != str(source or "").strip() or ticket_rel != str(
        rel or ""
    ).replace("\\", "/").strip():
        return JSONResponse(fail("图片凭证无效"), status_code=401)
    try:
        return image_response(rel, source)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
