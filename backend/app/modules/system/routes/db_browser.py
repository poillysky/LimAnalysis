"""system 子路由：数据库浏览（只读预览 + 管理员清空/导出）。

拆自原 system/router.py。危险操作（clear）已挂 require_admin。

筛选口径：`filters` 是 URL 参数上的 **JSON 字符串**，形如
`{"project_id":"eagle_rcvr","defect_item":"烟囱溢胶"}`，按等值 AND 组合；
与 `time_from` / `time_to` 可任意叠加。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_admin
from app.core.db_browser import (
    clear_table,
    column_values,
    ensure_engines,
    list_tables,
    normalize_filters,
    prepare_table_download,
    table_preview,
    target_info,
)
from app.core.response import fail, ok

router = APIRouter()


def _filters(raw: str | None) -> dict[str, str]:
    """把 HTTP 上的 filters 参数解析成 {列名: 值}；非法输入抛 ValueError。"""
    return normalize_filters(raw)


@router.get("/db/{target}/info")
def db_target_info(target: str):
    try:
        ensure_engines(target)
        return ok(target_info(target))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/db/{target}/tables")
def db_tables(target: str):
    try:
        ensure_engines(target)
        info = target_info(target)
        tables = list_tables(target) if info["ok"] else []
        return ok({"info": info, "tables": tables})
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/db/{target}/tables/{table}")
def db_table_rows(
    target: str,
    table: str,
    limit: int = 50,
    offset: int = 0,
    time_from: str | None = None,
    time_to: str | None = None,
    filters: str | None = None,
):
    try:
        ensure_engines(target)
        return ok(
            table_preview(
                target,
                table,
                limit=limit,
                offset=offset,
                time_from=time_from,
                time_to=time_to,
                filters=_filters(filters),
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/db/{target}/tables/{table}/values")
def db_table_column_values(
    target: str,
    table: str,
    column: str,
    filters: str | None = None,
    limit: int = 200,
):
    """某列的去重取值，给前端做筛选下拉（可带其它列做级联）。"""
    try:
        ensure_engines(target)
        return ok(
            {
                "column": column,
                "values": column_values(
                    target,
                    table,
                    column,
                    filters=_filters(filters),
                    limit=limit,
                ),
            }
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.post("/db/{target}/tables/{table}/clear")
def db_table_clear(target: str, table: str, _admin: dict = Depends(require_admin)):
    try:
        return ok(clear_table(target, table))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except RuntimeError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/db/{target}/tables/{table}/export")
def db_table_export(
    target: str,
    table: str,
    time_from: str | None = None,
    time_to: str | None = None,
    filters: str | None = None,
    _admin: dict = Depends(require_admin),
):
    import contextlib
    import os

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    try:
        payload = prepare_table_download(
            target,
            table,
            time_from=time_from,
            time_to=time_to,
            filters=_filters(filters),
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except RuntimeError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)

    path = payload["path"]

    def _cleanup() -> None:
        with contextlib.suppress(Exception):
            os.unlink(path)

    return FileResponse(
        path,
        filename=payload["filename"],
        media_type=payload["media_type"],
        background=BackgroundTask(_cleanup),
    )
