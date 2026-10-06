import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.db import MetaSession
from app.core.meta_init import init_meta_store
from app.core.meta_models import MetaProject, MetaSfcLog
from app.core.projects import load_projects
from app.core.sfc_accounts import enabled_accounts_with_password, mark_account
from app.core.sfc_config import load_sfc_config, patch_sfc_config
from collector.raw_loader import (
    align_column_order,
    decode_csv,
    drop_stale_columns,
    ensure_conflict_target,
    ensure_table,
    parse_csv,
    purge_empty_pk_rows,
    relax_legacy_primary_key,
    table_name,
    unique_column,
    unique_idents,
    upsert_dataframe,
)
from collector.sfc_client import (
    AccountError,
    NetworkUnreachableError,
    SessionExpiredError,
    download_project_csv,
    login_with_pool,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_csv(project_id: str, content: bytes) -> Path:
    path = settings.raw_csv_dir / f"{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path.write_bytes(content)
    return path


def _append_log(log_id: int, **fields) -> None:
    init_meta_store()
    db = MetaSession()
    try:
        row = db.get(MetaSfcLog, log_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _create_log(trigger: str) -> int:
    init_meta_store()
    db = MetaSession()
    try:
        row = MetaSfcLog(
            started_at=_now(),
            trigger=trigger,
            status="running",
            message="采集进行中",
            detail={"lines": []},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _touch_project(project_id: str, ok: bool, rows: int, message: str) -> None:
    db = MetaSession()
    try:
        row = db.get(MetaProject, project_id)
        if row is None:
            return
        config = dict(row.config or {})
        config["last_crawl_time"] = _now()
        config["last_crawl_status"] = "success" if ok else "failed"
        config["last_crawl_rows"] = rows
        config["last_crawl_message"] = message[:200]
        row.config = config
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_recent_logs(limit: int = 20) -> list[dict]:
    init_meta_store()
    db = MetaSession()
    try:
        rows = db.scalars(select(MetaSfcLog).order_by(MetaSfcLog.id.desc()).limit(limit)).all()
        return [
            {
                "id": row.id,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "trigger": row.trigger,
                "status": row.status,
                "message": row.message,
                "detail": row.detail or {},
            }
            for row in rows
        ]
    finally:
        db.close()


def clear_logs() -> dict:
    """清除采集日志。进行中的记录保留，避免打断当前任务展示。"""
    init_meta_store()
    db = MetaSession()
    try:
        result = db.execute(
            delete(MetaSfcLog).where(MetaSfcLog.status != "running")
        )
        db.commit()
        return {"deleted": int(result.rowcount or 0)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def crawl_status() -> dict:
    config = load_sfc_config()
    return {
        "is_running": bool(config.get("is_running")),
        "is_active": bool(config.get("is_active")),
        "last_run_time": config.get("last_run_time") or "",
        "last_run_status": config.get("last_run_status") or "",
        "logs": list_recent_logs(),
    }


def request_crawl(trigger: str = "manual") -> dict:
    """API / 调度：只投递采集任务，由 Worker 执行。"""
    from collector.jobs import JOB_CRAWL, enqueue_job, find_active_job

    active = find_active_job(JOB_CRAWL)
    if active:
        return {
            "accepted": False,
            "job_id": active["id"],
            "message": "已有采集任务排队或执行中",
            "status": active["status"],
        }
    job = enqueue_job(
        JOB_CRAWL,
        {"trigger": trigger},
        message=f"crawl queued ({trigger})",
    )
    return {
        "accepted": True,
        "job_id": job["id"],
        "message": "已入队，等待 Worker 执行",
        "status": job["status"],
    }


def execute_crawl(trigger: str = "manual") -> dict:
    """Worker：同步执行采集（不在 API 进程内起线程）。"""
    config = load_sfc_config()
    if config.get("is_running"):
        raise RuntimeError("已有采集在运行（is_running）")
    patch_sfc_config({"is_running": True, "last_run_status": "running"})
    log_id = _create_log(trigger)
    try:
        _run_job(trigger, log_id)
        return {"ok": True, "log_id": log_id, "trigger": trigger}
    except Exception:
        try:
            patch_sfc_config({"is_running": False, "last_run_status": "failed"})
        except Exception:
            logger.exception("采集失败后清除 is_running 失败")
        raise


# 兼容旧名：勿在 API 进程调用执行逻辑
def crawl_all(trigger: str = "manual") -> dict:
    return request_crawl(trigger=trigger)


def clear_stale_running() -> None:
    """进程重启后清掉残留的 is_running，避免任务永久假死。"""
    config = load_sfc_config()
    if not config.get("is_running"):
        return
    patch_sfc_config({"is_running": False})
    logger.warning("已清除残留的 is_running 标记")


def _finish_job(
    log_id: int,
    *,
    status: str,
    message: str,
    lines: list[dict],
) -> None:
    try:
        patch_sfc_config(
            {
                "is_running": False,
                "last_run_time": _now(),
                "last_run_status": status,
            }
        )
    except Exception:
        logger.exception("清除 is_running 失败")
    try:
        _append_log(
            log_id,
            ended_at=_now(),
            status=status,
            message=message,
            detail={"lines": lines[-200:]},
        )
    except Exception:
        logger.exception("写采集日志失败")


def _run_job(trigger: str, log_id: int) -> None:
    lines = []
    ok_count = 0
    fail_count = 0
    status = "failed"
    message = "采集异常退出"

    def add(level: str, message_text: str):
        item = {"time": _now(), "level": level, "message": message_text}
        lines.append(item)
        logger.info("%s %s", level, message_text)

    try:
        config = load_sfc_config()
        retry = int(config.get("retry") or 3)
        accounts = enabled_accounts_with_password()
        session, account, login_logs = login_with_pool(config, accounts, retry=retry)
        lines.extend(login_logs)
        if session is None:
            if account:
                mark_account(account["id"], False, "登录失败")
            raise RuntimeError("SFC 登录失败")
        mark_account(account["id"], True)
        projects = [item for item in load_projects() if item.get("enabled")]
        if not projects:
            add("warning", "没有启用的项目")
        for project in projects:
            sfc_code = str(project.get("sfc_code") or project.get("display_name") or "").strip()
            btype = str(project.get("btype") or "all").strip() or "all"
            name = project.get("display_name") or project["project_id"]
            if not sfc_code:
                add("warning", f"{name} 未配置 sfc_code，跳过")
                fail_count += 1
                continue
            csv_path = None
            try:
                add("info", f"下载 {name} p={sfc_code} type={btype}")
                content = download_project_csv(
                    session,
                    config,
                    {"sfc_code": sfc_code, "btype": btype},
                    retry=retry,
                )
                csv_path = _write_csv(project["project_id"], content)
                text = decode_csv(content)
                frame = parse_csv(text)
                result = upsert_dataframe(
                    frame, str(project.get("prefix") or ""), project["project_id"]
                )
                csv_path.unlink(missing_ok=True)
                csv_path = None
                rows = int(result.get("total") or 0)
                add("success", f"{name} 入库 {rows} 行 → {result.get('table')}")
                _touch_project(project["project_id"], True, rows, "ok")
                ok_count += 1
            except SessionExpiredError as exc:
                add("error", f"{name}: {exc}")
                _touch_project(project["project_id"], False, 0, str(exc))
                fail_count += 1
                session, account, relog = login_with_pool(config, accounts, retry=retry)
                lines.extend(relog)
                if session is None:
                    raise RuntimeError("重新登录失败")
            except Exception as exc:
                add("error", f"{name}: {exc}")
                _touch_project(project["project_id"], False, 0, str(exc))
                fail_count += 1
            finally:
                if csv_path and csv_path.exists():
                    add("warning", f"保留失败文件 {csv_path.name}")
        status = "success" if fail_count == 0 else ("partial" if ok_count else "failed")
        message = f"成功 {ok_count}，失败 {fail_count}"
    except Exception as exc:
        add("error", str(exc))
        status = "failed"
        message = str(exc)[:500]
    finally:
        _finish_job(log_id, status=status, message=message, lines=lines)


def sync_project_schema(project_id: str, content: bytes) -> dict:
    """Worker：按 CSV 表头对齐 raw 表结构。"""
    return _sync_project_schema_unlocked(project_id, content)


def execute_sync_schema_file(project_id: str, file_path: str) -> dict:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"文件不存在: {file_path}")
    return sync_project_schema(project_id, path.read_bytes())


def _sync_project_schema_unlocked(project_id: str, content: bytes) -> dict:
    project_id = str(project_id or "").strip()
    if not project_id:
        raise ValueError("请选择项目")
    if not content:
        raise ValueError("文件为空")
    projects = {item["project_id"]: item for item in load_projects()}
    project = projects.get(project_id)
    if project is None:
        raise ValueError("项目不存在")
    prefix = str(project.get("prefix") or project_id)
    frame = parse_csv(decode_csv(content))
    if frame.empty and len(frame.columns) == 0:
        raise ValueError("CSV 无表头")
    pk_src = unique_column(frame)
    sql_cols = unique_idents([str(c) for c in frame.columns])
    rename = {str(s): d for s, d in zip(frame.columns, sql_cols)}
    if pk_src not in rename:
        raise ValueError("唯一键列不在 CSV 表头中")
    pk = rename[pk_src]
    table = table_name(prefix, project_id)
    from app.core import db as stores

    engine = stores.raw_engine

    ensure_table(engine, table, sql_cols, pk)
    relax_legacy_primary_key(engine, table, pk)
    dropped = drop_stale_columns(engine, table, sql_cols)
    reordered = align_column_order(engine, table, sql_cols, pk)
    ensure_conflict_target(engine, table, pk)
    purged = purge_empty_pk_rows(engine, table, pk)
    return {
        "project_id": project_id,
        "table": table,
        "unique_key": pk,
        "columns": len(sql_cols),
        "dropped_columns": dropped,
        "reordered": reordered,
        "purged_empty_rows": purged,
        "schema_sync_v": 2,
    }


def upload_project_csv(project_id: str, content: bytes, filename: str = "") -> dict:
    """Worker：手动上传 CSV 入库。"""
    return _upload_project_csv_unlocked(project_id, content, filename)


def execute_upload_file(
    project_id: str, file_path: str, filename: str = ""
) -> dict:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"文件不存在: {file_path}")
    return upload_project_csv(
        project_id, path.read_bytes(), filename or path.name
    )


def _upload_project_csv_unlocked(
    project_id: str, content: bytes, filename: str = ""
) -> dict:
    project_id = str(project_id or "").strip()
    if not project_id:
        raise ValueError("请选择项目")
    if not content:
        raise ValueError("文件为空")
    projects = {item["project_id"]: item for item in load_projects()}
    project = projects.get(project_id)
    if project is None:
        raise ValueError("项目不存在")
    name = project.get("display_name") or project_id
    prefix = str(project.get("prefix") or project_id)
    log_id = _create_log("upload")
    lines = [
        {
            "time": _now(),
            "level": "info",
            "message": f"手动上传 {name} ← {filename or 'csv'}",
        }
    ]
    try:
        text = decode_csv(content)
        frame = parse_csv(text)
        if frame.empty:
            raise ValueError("CSV 无有效数据")
        result = upsert_dataframe(frame, prefix, project_id)
        rows = int(result.get("total") or 0)
        table = result.get("table") or f"{prefix}_raw"
        lines.append(
            {
                "time": _now(),
                "level": "success",
                "message": f"{name} 入库 {rows} 行 → {table}",
            }
        )
        _touch_project(project_id, True, rows, "upload ok")
        _finish_job(
            log_id,
            status="success",
            message=f"{name} 上传入库 {rows} 行",
            lines=lines,
        )
        dropped = result.get("dropped_columns") or []
        if dropped:
            lines.append(
                {
                    "time": _now(),
                    "level": "info",
                    "message": f"{name} 清理历史脏列 {len(dropped)} 个: {', '.join(dropped[:12])}"
                    + ("…" if len(dropped) > 12 else ""),
                }
            )
        return {
            "project_id": project_id,
            "display_name": name,
            "rows": rows,
            "table": table,
            "unique_key": result.get("unique_key"),
            "dropped_columns": dropped,
            "log_id": log_id,
        }
    except Exception as exc:
        lines.append({"time": _now(), "level": "error", "message": str(exc)})
        _touch_project(project_id, False, 0, str(exc))
        _finish_job(
            log_id,
            status="failed",
            message=str(exc)[:500],
            lines=lines,
        )
        raise
