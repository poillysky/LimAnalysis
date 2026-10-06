"""数据清洗：字段映射配置 + 投递 etl_clean 任务。"""

from app.core.projects import load_projects
from app.core.response import fail, ok
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/etl", tags=["etl"])


class EtlRunBody(BaseModel):
    project_id: str = Field(default="", description="空且无 model_id=全部可跑模型")
    model_id: int | None = Field(default=None, description="指定模型 ID")
    full_refresh: bool = Field(default=False, description="true=全量重建；默认增量")


class EtlModelUpdate(BaseModel):
    name: str | None = None
    unique_key: str | None = None
    incremental_field: str | None = None
    is_enabled: bool | None = None


class EtlFieldItem(BaseModel):
    source_field: str = ""
    target_field: str
    field_type: str = "text"
    mapping_type: str = "direct"
    derive_level: int = 1
    formula: str = ""
    constant_value: str = ""
    sort_order: int = 0
    is_required: bool = False
    description: str = ""


class EtlFieldsBody(BaseModel):
    fields: list[EtlFieldItem]


class EtlPreviewBody(BaseModel):
    limit: int = 50


@router.get("/field-types")
def field_types():
    from processor.field_types import FIELD_TYPES

    return ok({"types": FIELD_TYPES})


class EtlSchedulerUpdate(BaseModel):
    is_active: bool | None = None
    run_interval: int | None = Field(default=None, description="分钟")


@router.get("/overview")
def overview():
    from app.core.etl_config import load_etl_config
    from collector.jobs import JOB_ETL_CLEAN, find_active_job
    from processor.models_store import list_models

    active = find_active_job(JOB_ETL_CLEAN)
    models = list_models()
    by_project = {m["project_id"]: m for m in models}
    projects = []
    for item in load_projects():
        cfg = item if isinstance(item, dict) else {}
        pid = cfg.get("project_id")
        model = by_project.get(pid) or {}
        prefix = str(cfg.get("prefix") or pid or "")
        projects.append(
            {
                "project_id": pid,
                "display_name": cfg.get("display_name"),
                "enabled": cfg.get("enabled"),
                "prefix": prefix,
                "source_table": model.get("source_table")
                or (f"{prefix}_raw" if prefix else ""),
                "target_table": model.get("target_table")
                or (f"{prefix}_dwd" if prefix else ""),
                "model_id": model.get("id"),
                "is_draft": model.get("is_draft", True),
                "is_model_enabled": model.get("is_enabled", False),
                "can_run": model.get("can_run", False),
                "field_count": model.get("field_count", 0),
                "last_etl_time": model.get("last_run_time")
                or cfg.get("last_etl_time")
                or "",
                "last_etl_status": model.get("last_run_status")
                or cfg.get("last_etl_status")
                or "",
                "last_etl_rows": model.get("last_run_rows")
                or cfg.get("last_etl_rows")
                or 0,
                "last_etl_message": model.get("last_run_message")
                or cfg.get("last_etl_message")
                or "",
                "last_crawl_rows": cfg.get("last_crawl_rows") or 0,
            }
        )
    return ok(
        {
            "projects": projects,
            "models": models,
            "active_job": active,
            "scheduler": load_etl_config(),
        }
    )


@router.get("/scheduler")
def get_scheduler():
    from app.core.etl_config import load_etl_config

    return ok(load_etl_config())


@router.put("/scheduler")
def put_scheduler(body: EtlSchedulerUpdate):
    from app.core.etl_config import save_etl_config

    try:
        return ok(save_etl_config(body.model_dump(exclude_unset=True)))
    except Exception as exc:
        return JSONResponse(fail(f"保存失败: {exc}"), status_code=400)


@router.get("/models")
def get_models():
    from processor.models_store import list_models

    return ok({"models": list_models()})


@router.post("/models")
def create_or_ensure_model(body: dict | None = None):
    from processor.models_store import ensure_model_for_project

    body = body or {}
    pid = str(body.get("project_id") or "").strip()
    if not pid:
        return JSONResponse(fail("缺少 project_id"), status_code=400)
    try:
        return ok(ensure_model_for_project(pid))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/models/{model_id}")
def get_model_detail(model_id: int):
    from processor.models_store import get_model

    model = get_model(model_id, include_fields=True)
    if model is None:
        return JSONResponse(fail("模型不存在"), status_code=404)
    return ok(model)


@router.put("/models/{model_id}")
def put_model(model_id: int, body: EtlModelUpdate):
    from processor.models_store import update_model

    try:
        return ok(update_model(model_id, body.model_dump(exclude_unset=True)))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/models/{model_id}/source-columns")
def source_columns(model_id: int):
    from processor.models_store import list_source_columns

    try:
        return ok({"columns": list_source_columns(model_id)})
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/models/{model_id}/fields")
def get_fields(model_id: int):
    from processor.models_store import get_model, list_fields

    if get_model(model_id, include_fields=False) is None:
        return JSONResponse(fail("模型不存在"), status_code=404)
    return ok({"fields": list_fields(model_id)})


@router.put("/models/{model_id}/fields")
def put_fields(model_id: int, body: EtlFieldsBody):
    from processor.models_store import save_fields

    try:
        payload = [f.model_dump() for f in body.fields]
        return ok(save_fields(model_id, payload))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/fields/import-direct")
def import_direct(model_id: int):
    from processor.models_store import import_direct_fields

    try:
        return ok(import_direct_fields(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/models/{model_id}/fields")
def delete_fields(model_id: int):
    from processor.models_store import clear_all_config

    try:
        return ok(clear_all_config(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


class EtlSourceFieldItem(BaseModel):
    source_field: str
    field_type: str = "text"
    sort_order: int = 0


class EtlSourceFieldsBody(BaseModel):
    source_fields: list[EtlSourceFieldItem]


@router.put("/models/{model_id}/source-fields")
def put_source_fields(model_id: int, body: EtlSourceFieldsBody):
    from processor.models_store import save_source_fields

    try:
        payload = [f.model_dump() for f in body.source_fields]
        return ok(save_source_fields(model_id, payload))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/source-fields/reanalyze")
def post_reanalyze_source_fields(model_id: int):
    """按列名+采样重新识别原表字段类型（不删清洗映射）。"""
    from processor.models_store import reanalyze_source_field_types

    try:
        return ok(reanalyze_source_field_types(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


class FormulaGenerateBody(BaseModel):
    prompt: str = ""
    hint_field: str = ""
    available_fields: list[str] = Field(default_factory=list)
    # auto=AI 就绪则优先 AI，失败回退规则；ai=仅 AI；rules=仅规则
    mode: str = "auto"


@router.get("/formula/help")
def get_formula_help():
    from app.core.ai_config import load_ai_config_public
    from processor.formula_assistant import list_formula_help

    help_data = list_formula_help()
    help_data["ai"] = load_ai_config_public()
    return ok(help_data)


@router.post("/models/{model_id}/formula/generate")
def post_generate_formula(model_id: int, body: FormulaGenerateBody):
    """中文描述 → 派生公式：优先 AI，失败回退规则。"""
    from app.core.ai_client import generate_etl_formula_with_ai
    from app.core.ai_config import load_ai_config_public
    from processor.formula_assistant import (
        PROMPT_EXAMPLES,
        generate_formula_from_prompt,
    )
    from processor.models_store import get_model

    try:
        model = get_model(model_id, include_fields=True)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)

    fields = list(body.available_fields or [])
    if not fields:
        for item in model.get("source_fields") or []:
            name = str(item.get("source_field") or "").strip()
            if name:
                fields.append(name)
        for item in model.get("fields") or []:
            name = str(item.get("target_field") or "").strip()
            if name and name not in fields:
                fields.append(name)

    mode = (body.mode or "auto").strip().lower()
    ai_info = load_ai_config_public()
    use_ai = mode == "ai" or (mode == "auto" and ai_info.get("ready"))

    ai_error = ""
    if use_ai:
        ai_result = generate_etl_formula_with_ai(
            body.prompt,
            available_fields=fields,
            hint_field=body.hint_field or None,
            source_kind="raw",
        )
        if ai_result.get("ok"):
            ai_result["examples"] = PROMPT_EXAMPLES
            ai_result["available_fields"] = fields[:40]
            ai_result["ai"] = ai_info
            return ok(ai_result)
        ai_error = str(ai_result.get("error") or "AI 失败")
        if mode == "ai":
            ai_result["examples"] = PROMPT_EXAMPLES
            ai_result["ai"] = ai_info
            return ok(ai_result)

    result = generate_formula_from_prompt(
        body.prompt,
        available_fields=fields,
        hint_field=body.hint_field or None,
        source_kind="raw",
    )
    result["source"] = "rules"
    result["ai"] = ai_info
    if ai_error:
        result["ai_fallback_error"] = ai_error
        if result.get("ok") and result.get("explanation"):
            result["explanation"] = f"{result['explanation']}（规则生成；AI：{ai_error}）"
    return ok(result)


@router.get("/models/{model_id}/sql-preview")
def get_sql_preview(model_id: int):
    from processor.executor import sql_preview

    try:
        return ok(sql_preview(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/preview")
def post_preview(model_id: int, body: EtlPreviewBody | None = None):
    from processor.executor import preview_model

    body = body or EtlPreviewBody()
    try:
        return ok(preview_model(model_id, limit=body.limit))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(f"预览失败: {exc}"), status_code=400)


@router.post("/run")
def run_etl(body: EtlRunBody):
    from processor.runner import request_etl

    pid = (body.project_id or "").strip() or None
    mid = body.model_id
    if pid:
        ids = {p["project_id"] for p in load_projects()}
        if pid not in ids:
            return JSONResponse(fail("项目不存在"), status_code=400)
    try:
        result = request_etl(
            project_id=pid,
            model_id=mid,
            trigger="manual",
            full_refresh=bool(body.full_refresh),
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    if not result.get("accepted"):
        return JSONResponse(fail(result.get("message") or "无法入队"), status_code=409)
    return ok(result)


@router.get("/jobs/{job_id}")
def get_job_status(job_id: int):
    from collector.jobs import get_job

    job = get_job(job_id)
    if job is None:
        return JSONResponse(fail("任务不存在"), status_code=404)
    return ok(job)
