"""数据聚合：DWD → ADS，投递 etl_agg 给独立 Worker。"""

from app.core.projects import load_projects
from app.core.response import fail, ok
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agg", tags=["agg"])


class AggRunBody(BaseModel):
    project_id: str = Field(default="")
    model_id: int | None = None
    full_refresh: bool = False


class AggSchedulerUpdate(BaseModel):
    is_active: bool | None = None


class AggFieldItem(BaseModel):
    source_field: str = ""
    target_field: str
    field_type: str = "text"
    field_category: str = "dimension"
    aggregate_func: str = ""
    derive_level: int = 1
    formula: str = ""
    sort_order: int = 0
    description: str = ""


class AggSaveBody(BaseModel):
    time_field: str | None = None
    granularity: str | None = None
    time_field_name: str | None = None
    lookback_hours: int | None = None
    backfill_hours: int | None = None
    is_enabled: bool | None = None
    fields: list[AggFieldItem]


class FormulaGenerateBody(BaseModel):
    prompt: str = ""
    hint_field: str = ""
    available_fields: list[str] = Field(default_factory=list)
    mode: str = "auto"


class AggQueryBody(BaseModel):
    hours: int | None = None
    limit: int = 200
    live: bool = False


@router.get("/overview")
def overview():
    from app.core.agg_config import load_agg_config
    from collector.jobs import JOB_ETL_AGG, find_active_job
    from processor.agg_store import list_models

    active = find_active_job(JOB_ETL_AGG)
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
                or (f"{prefix}_dwd" if prefix else ""),
                "target_table": model.get("target_table")
                or (f"{prefix}_ads" if prefix else ""),
                "model_id": model.get("id"),
                "is_draft": model.get("is_draft", True),
                "is_model_enabled": model.get("is_enabled", False),
                "can_run": model.get("can_run", False),
                "field_count": model.get("field_count", 0),
                "lookback_hours": model.get("lookback_hours") or 1,
                "granularity": model.get("granularity") or "hour",
                "last_agg_time": model.get("last_run_time") or "",
                "last_agg_status": model.get("last_run_status") or "",
                "last_agg_rows": model.get("last_run_rows") or 0,
                "last_agg_message": model.get("last_run_message") or "",
            }
        )
    return ok(
        {
            "projects": projects,
            "models": models,
            "active_job": active,
            "scheduler": load_agg_config(),
        }
    )


@router.get("/scheduler")
def get_scheduler():
    from app.core.agg_config import load_agg_config

    return ok(load_agg_config())


@router.put("/scheduler")
def put_scheduler(body: AggSchedulerUpdate):
    from app.core.agg_config import save_agg_config

    return ok(
        save_agg_config(
            {
                "is_active": body.is_active,
            }
        )
    )


@router.post("/models")
def post_model(body: dict):
    from processor.agg_store import ensure_model_for_project

    pid = str((body or {}).get("project_id") or "").strip()
    if not pid:
        return JSONResponse(fail("缺少 project_id"), status_code=400)
    try:
        return ok(ensure_model_for_project(pid))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/models/{model_id}")
def get_one(model_id: int):
    from processor.agg_store import get_model

    model = get_model(model_id, include_fields=True)
    if model is None:
        return JSONResponse(fail("模型不存在"), status_code=404)
    return ok(model)


@router.put("/models/{model_id}")
def put_one(model_id: int, body: dict):
    from processor.agg_store import update_model

    try:
        return ok(update_model(model_id, body or {}))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/models/{model_id}/source-columns")
def source_columns(model_id: int):
    from processor.agg_store import list_dwd_columns

    try:
        return ok({"columns": list_dwd_columns(model_id)})
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/suggest")
def suggest(model_id: int):
    from processor.agg_store import suggest_fields

    try:
        return ok(suggest_fields(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.put("/models/{model_id}/config")
def put_config(model_id: int, body: AggSaveBody):
    from processor.agg_store import save_model_config

    try:
        payload = body.model_dump()
        payload["fields"] = [f.model_dump() for f in body.fields]
        return ok(save_model_config(model_id, payload))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/formula/generate")
def post_generate_formula(model_id: int, body: FormulaGenerateBody):
    from app.core.ai_client import generate_etl_formula_with_ai
    from app.core.ai_config import load_ai_config_public
    from processor.agg_store import get_model, list_dwd_columns
    from processor.formula_assistant import (
        PROMPT_EXAMPLES,
        generate_formula_from_prompt,
    )

    model = get_model(model_id, include_fields=True)
    if model is None:
        return JSONResponse(fail("模型不存在"), status_code=404)

    fields = list(body.available_fields or [])
    if not fields:
        for item in model.get("fields") or []:
            name = str(item.get("target_field") or "").strip()
            if name and name not in fields:
                fields.append(name)
        for col in list_dwd_columns(model_id):
            name = str(col.get("column_name") or "").strip()
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
            source_kind="typed",
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
        source_kind="typed",
    )
    result["source"] = "rules"
    result["ai"] = ai_info
    if ai_error:
        result["ai_fallback_error"] = ai_error
        if result.get("ok") and result.get("explanation"):
            result["explanation"] = f"{result['explanation']}（规则生成；AI：{ai_error}）"
    return ok(result)


@router.get("/models/{model_id}/sql-preview")
def get_sql(model_id: int):
    from processor.agg_executor import sql_preview

    try:
        return ok(sql_preview(model_id))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.post("/models/{model_id}/preview")
def post_preview(model_id: int, body: AggQueryBody | None = None):
    from processor.agg_executor import preview_model, query_ads

    body = body or AggQueryBody()
    try:
        if body.live:
            return ok(preview_model(model_id, hours=body.hours, limit=body.limit))
        return ok(query_ads(model_id, hours=body.hours, limit=body.limit))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(f"查询失败: {exc}"), status_code=400)


@router.post("/run")
def run_agg(body: AggRunBody):
    from processor.agg_runner import request_agg

    pid = (body.project_id or "").strip() or None
    if pid:
        ids = {p["project_id"] for p in load_projects()}
        if pid not in ids:
            return JSONResponse(fail("项目不存在"), status_code=400)
    try:
        result = request_agg(
            project_id=pid,
            model_id=body.model_id,
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
