"""数据清洗任务：API 投递，Worker 按字段映射执行。"""

from __future__ import annotations

import logging
import time

from collector.jobs import JOB_ETL_CLEAN, enqueue_job, find_active_job
from processor.etl_logs import log_line
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
    from processor.etl_logs import log_line

    kind = "full" if full_refresh else "incremental"
    t0 = time.time()
    lines: list[dict] = [
        log_line("info", f"开始清洗（模式={'全量' if full_refresh else '增量'}）")
    ]
    try:
        if model_id:
            lines.append(log_line("info", f"执行模型 #{int(model_id)}"))
            result = execute_model(int(model_id), full_refresh=full_refresh)
            lines.append(
                log_line(
                    "success" if result.get("ok", True) else "error",
                    str(result.get("message") or "完成"),
                )
            )
            return {
                "ok": True,
                "run_scope": "one",
                "run_mode": result.get("mode") or kind,
                "duration": round(time.time() - t0, 3),
                **result,
                "execution_logs": lines,
            }
        if all_enabled or not project_id:
            lines.append(log_line("info", "执行全部已启用模型"))
            result = execute_all_enabled(full_refresh=full_refresh)
            for item in result.get("projects") or []:
                lines.append(
                    log_line(
                        "success",
                        f"{item.get('project_id')}: {item.get('message') or item.get('rows')} 行",
                    )
                )
            for err in result.get("errors") or []:
                lines.append(
                    log_line(
                        "error",
                        f"{err.get('project_id') or err.get('model_id')}: {err.get('error')}",
                    )
                )
            ok = bool(result.get("ok"))
            if ok:
                total = int(result.get("total_rows") or 0)
                ins = int(result.get("total_inserted") or 0)
                upd = int(result.get("total_updated") or 0)
                summary = f"合计写入 {total} 行（新增 {ins} / 更新 {upd}）"
            else:
                summary = f"部分失败（{len(result.get('errors') or [])}）"
            lines.append(log_line("success" if ok else "error", summary))
            return {
                "ok": ok,
                "run_scope": "all",
                "run_mode": kind,
                "duration": round(time.time() - t0, 3),
                **result,
                "execution_logs": lines,
            }
        lines.append(log_line("info", f"执行项目 {project_id}"))
        result = execute_project(str(project_id), full_refresh=full_refresh)
        lines.append(
            log_line(
                "success" if result.get("ok", True) else "error",
                str(result.get("message") or "完成"),
            )
        )
        return {
            "ok": True,
            "run_scope": "one",
            "run_mode": result.get("mode") or kind,
            "duration": round(time.time() - t0, 3),
            **result,
            "execution_logs": lines,
        }
    except Exception as exc:
        lines.append(log_line("error", str(exc)[:400]))
        raise
