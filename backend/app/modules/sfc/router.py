from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.projects import load_projects, resolve_btype, resolve_sfc_code
from app.core.response import fail, ok
from app.core.sfc_accounts import (
    create_account,
    delete_account,
    list_accounts,
    update_account,
)
from app.core.sfc_config import load_sfc_config, save_sfc_config
from app.modules.sfc.schemas import SfcAccountCreate, SfcAccountUpdate, SfcConfigUpdate

router = APIRouter(prefix="/sfc", tags=["sfc"])


def _save_upload_file(project_id: str, filename: str, content: bytes) -> Path:
    safe_name = Path(filename or "upload.csv").name
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = settings.raw_csv_dir / f"{project_id}_{stamp}_{safe_name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


@router.get("/overview")
def overview():
    from collector.jobs import find_active_job
    from collector.runner import crawl_status

    config = load_sfc_config()
    status = crawl_status()
    active = find_active_job()
    projects = []
    for item in load_projects():
        cfg = item if isinstance(item, dict) else {}
        projects.append(
            {
                "project_id": cfg.get("project_id"),
                "display_name": cfg.get("display_name"),
                "enabled": cfg.get("enabled"),
                "sfc_code": resolve_sfc_code(
                    display_name=str(cfg.get("display_name") or ""),
                    prefix=str(cfg.get("prefix") or ""),
                    project_id=str(cfg.get("project_id") or ""),
                    current=str(cfg.get("sfc_code") or ""),
                ),
                "btype": resolve_btype(cfg.get("btype")),
                "prefix": cfg.get("prefix"),
                "last_crawl_time": (cfg.get("last_crawl_time") or ""),
                "last_crawl_status": (cfg.get("last_crawl_status") or ""),
                "last_crawl_rows": cfg.get("last_crawl_rows") or 0,
            }
        )
    public_config = {
        key: config.get(key)
        for key in (
            "sso_login_url",
            "sfc_base_url",
            "sfc_logon_path",
            "sfc_data_path",
            "line_option",
            "section_option",
            "crawl_interval",
            "retry",
            "is_active",
            "is_running",
            "last_run_time",
            "last_run_status",
        )
    }
    return ok(
        {
            "config": public_config,
            "accounts": list_accounts(),
            "projects": projects,
            "status": status,
            "active_job": active,
        }
    )


@router.get("/jobs/{job_id}")
def get_job_status(job_id: int):
    from collector.jobs import get_job

    job = get_job(job_id)
    if job is None:
        return JSONResponse(fail("任务不存在"), status_code=404)
    return ok(job)


@router.put("/config")
def put_config(body: SfcConfigUpdate):
    saved = save_sfc_config(body.model_dump(exclude_unset=True))
    return ok(saved)


@router.post("/accounts")
def add_account(body: SfcAccountCreate):
    try:
        return ok(create_account(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.put("/accounts/{account_id}")
def edit_account(account_id: int, body: SfcAccountUpdate):
    try:
        item = update_account(account_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    if item is None:
        return JSONResponse(fail("账号不存在"), status_code=404)
    return ok(item)


@router.delete("/accounts/{account_id}")
def remove_account(account_id: int):
    if not delete_account(account_id):
        return JSONResponse(fail("账号不存在"), status_code=404)
    return ok({"id": account_id})


@router.post("/run")
def run_now():
    from collector.runner import request_crawl

    result = request_crawl(trigger="manual")
    if not result.get("accepted"):
        return JSONResponse(fail(result.get("message") or "无法入队"), status_code=409)
    return ok(result)


@router.delete("/logs")
def remove_logs():
    from collector.runner import clear_logs

    return ok(clear_logs())


@router.post("/purge-empty-rows")
def purge_empty_rows(project_id: str = Form(...)):
    """轻量清理：空唯一键行。仍在 API 执行（秒级）。"""
    from app.core import db as stores
    from app.core.projects import load_projects, load_system_defaults
    from collector.raw_loader import purge_empty_pk_rows, table_name

    project_id = str(project_id or "").strip()
    projects = {item["project_id"]: item for item in load_projects()}
    project = projects.get(project_id)
    if project is None:
        return JSONResponse(fail("项目不存在"), status_code=400)

    pk = str(
        (project.get("unique_key") or {}).get("column")
        or (load_system_defaults().get("unique_key") or {}).get("column")
        or "FCoverSN"
    ).strip() or "FCoverSN"
    prefix = str(project.get("prefix") or project_id)
    table = table_name(prefix, project_id)
    try:
        stores.refresh_pg_engines()
        deleted = purge_empty_pk_rows(stores.raw_engine, table, pk)
        return ok(
            {
                "project_id": project_id,
                "table": table,
                "unique_key": pk,
                "deleted": deleted,
            }
        )
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.post("/sync-schema")
async def sync_schema(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    """投递表结构同步任务（Worker 执行）。"""
    from collector.jobs import JOB_SYNC_SCHEMA, enqueue_job

    project_id = str(project_id or "").strip()
    projects = {item["project_id"]: item for item in load_projects()}
    if project_id not in projects:
        return JSONResponse(fail("项目不存在"), status_code=400)
    content = await file.read()
    if len(content) > 80 * 1024 * 1024:
        return JSONResponse(fail("文件过大（上限 80MB）"), status_code=400)
    if not content:
        return JSONResponse(fail("文件为空"), status_code=400)
    path = _save_upload_file(project_id, file.filename or "schema.csv", content)
    job = enqueue_job(
        JOB_SYNC_SCHEMA,
        {
            "project_id": project_id,
            "file_path": str(path),
            "filename": file.filename or path.name,
        },
        message=f"sync-schema {project_id}",
    )
    return ok(
        {
            "accepted": True,
            "job_id": job["id"],
            "message": "已入队，等待 Worker 同步表结构",
            "status": job["status"],
        }
    )


@router.post("/upload")
async def upload_csv(
    project_id: str = Form(...),
    file: UploadFile = File(...),
):
    """投递上传入库任务（Worker 执行）。"""
    from collector.jobs import JOB_UPLOAD, enqueue_job

    project_id = str(project_id or "").strip()
    projects = {item["project_id"]: item for item in load_projects()}
    if project_id not in projects:
        return JSONResponse(fail("项目不存在"), status_code=400)
    name = (file.filename or "").lower()
    if name and not (name.endswith(".csv") or name.endswith(".txt")):
        return JSONResponse(fail("仅支持 CSV / TXT 文件"), status_code=400)
    content = await file.read()
    if len(content) > 80 * 1024 * 1024:
        return JSONResponse(fail("文件过大（上限 80MB）"), status_code=400)
    if not content:
        return JSONResponse(fail("文件为空"), status_code=400)
    path = _save_upload_file(project_id, file.filename or "upload.csv", content)
    job = enqueue_job(
        JOB_UPLOAD,
        {
            "project_id": project_id,
            "file_path": str(path),
            "filename": file.filename or path.name,
        },
        message=f"upload {project_id}",
    )
    return ok(
        {
            "accepted": True,
            "job_id": job["id"],
            "message": "已入队，等待 Worker 入库",
            "status": job["status"],
            "file_path": str(path),
        }
    )
