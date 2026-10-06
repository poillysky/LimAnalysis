from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.defect_scans import (
    bootstrap,
    import_sn_file,
    list_ops,
    load_analysis_alert_rules,
    load_project_items,
    query_defect_analysis,
    record_scan,
    record_scans,
    save_analysis_alert_rules,
    save_project_items,
)
from app.core.response import fail, ok
from app.modules.scan.schemas import DefectScanBatchIn, DefectScanCreate, DefectScanItemsIn
from app.modules.system.schemas import CavityAlertRulesIn

router = APIRouter(prefix="/scan", tags=["scan"])


@router.get("/defect/bootstrap")
def scan_bootstrap(project_id: str | None = None):
    try:
        return ok(bootstrap(project_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/defect/analysis")
def scan_analysis(
    project_id: str,
    defect_item: str | None = None,
    hours: int = Query(default=12, ge=1, le=72),
    exclude_machine_cavities: str = "",
    exclude_body_cavities: str = "",
):
    try:
        return ok(
            query_defect_analysis(
                project_id,
                hours=hours,
                defect_item=defect_item,
                exclude_machine_cavities=exclude_machine_cavities,
                exclude_body_cavities=exclude_body_cavities,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/defect/analysis-rules")
def scan_analysis_rules_get():
    return ok(load_analysis_alert_rules())


@router.put("/defect/analysis-rules")
def scan_analysis_rules_put(body: CavityAlertRulesIn):
    return ok(save_analysis_alert_rules(body.model_dump()))


@router.get("/defect/scans")
def scan_list(
    project_id: str | None = None,
    defect_item: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
):
    return ok(
        list_ops(
            project_id=project_id,
            defect_item=defect_item,
            limit=limit,
        )
    )


@router.get("/defect/items")
def scan_items_get(project_id: str):
    try:
        return ok(load_project_items(project_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.put("/defect/items")
def scan_items_put(body: DefectScanItemsIn):
    try:
        return ok(save_project_items(body.project_id, body.items))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/defect/scans")
def scan_create(body: DefectScanCreate):
    try:
        return ok(record_scan(body.project_id, body.defect_item, body.sn))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/defect/scans/batch")
def scan_batch(body: DefectScanBatchIn):
    try:
        return ok(record_scans(body.project_id, body.defect_item, body.sns))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/defect/scans/import")
async def scan_import(
    project_id: str = Form(),
    defect_item: str = Form(),
    file: UploadFile = File(),
):
    try:
        content = await file.read()
        return ok(
            import_sn_file(
                project_id,
                defect_item,
                file.filename or "upload.txt",
                content,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
