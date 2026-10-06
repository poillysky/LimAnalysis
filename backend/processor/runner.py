"""数据清洗任务：API 投递，Worker 按字段映射执行。"""

from __future__ import annotations

import logging

from collector.jobs import JOB_ETL_CLEAN, enqueue_job, find_active_job
from processor.executor import execute_all_enabled, execute_model, execute_project
from processor.models_store import assert_model_runnable, get_model, get_model_by_project

logger = logging.getLogger(__name__)


def request_etl(
    *,
    project_id: str | None = None,
    model_id: int | None = None,
    trigger: str = "manual",
    full_refresh: bool = False,
) -> dict:
    active = find_active_job(JOB_ETL_CLEAN)
    if active:
        return {
            "accepted": False,
            "job_id": active["id"],
            "message": "已有清洗任务排队或执行中",
            "status": active["status"],
        }

    payload: dict = {"trigger": trigger, "full_refresh": bool(full_refresh)}
    mid = int(model_id) if model_id else None
    pid = str(project_id or "").strip() or None

    if mid:
        model = get_model(mid, include_fields=True)
        assert_model_runnable(model)
        payload["model_id"] = mid
        payload["project_id"] = model["project_id"]
    elif pid:
        model = get_model_by_project(pid, include_fields=True)
        assert_model_runnable(model)
        payload["model_id"] = int(model["id"])
        payload["project_id"] = pid
    else:
        # 全部：至少有一个可跑
        from processor.models_store import list_models

        runnable = [m for m in list_models() if m.get("can_run")]
        if not runnable:
            raise ValueError(
                "没有可执行的已启用模型（请先配置字段映射、保存生成 SQL 并启用）"
            )
        payload["all_enabled"] = True

    kind = "full" if full_refresh else "incremental"
    job = enqueue_job(
        JOB_ETL_CLEAN,
        payload,
        message=f"etl_clean queued ({trigger}, {kind})",
    )
    return {
        "accepted": True,
        "job_id": job["id"],
        "message": "已入队，等待 Worker 清洗",
        "status": job["status"],
    }


def execute_etl(
    *,
    project_id: str | None = None,
    model_id: int | None = None,
    all_enabled: bool = False,
    full_refresh: bool = False,
) -> dict:
    if model_id:
        result = execute_model(int(model_id), full_refresh=full_refresh)
        return {"ok": True, "run_scope": "one", **result}
    if all_enabled or not project_id:
        result = execute_all_enabled(full_refresh=full_refresh)
        return {"ok": bool(result.get("ok")), "run_scope": "all", **result}
    result = execute_project(str(project_id), full_refresh=full_refresh)
    return {"ok": True, "run_scope": "one", **result}
