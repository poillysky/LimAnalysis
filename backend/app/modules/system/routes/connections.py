"""system 子路由：连接与存储状态。

拆自原 668 行的 system/router.py，按其职责拆分，降低单文件体量。
每个子路由保留 /system 前缀，由 system/router.py 统一 include。
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_admin
from app.core import db as stores
from app.core.connections import (
    ping_dbweb,
    ping_metabase,
    ping_parts,
    public_connections,
    public_dbweb,
    public_metabase,
    save_connections,
    save_dbweb,
    save_metabase,
)
from app.core.metabase_embed import board_for_project
from app.core.response import ok
from app.modules.system.schemas import (
    ConnectionsUpdate,
    ConnectionTest,
    DbwebTest,
    MetabaseTest,
)

router = APIRouter()


@router.get("/stores")
def store_status():
    stores.refresh_pg_engines()
    return ok(
        {
            "meta": stores.ping_engine(stores.meta_engine),
            "raw": stores.ping_engine(stores.raw_engine),
            "dwh": stores.ping_engine(stores.dwh_engine),
            "defect": stores.ping_engine(stores.defect_engine),
        }
    )


def _connections_payload() -> dict:
    dbweb = public_dbweb()
    metabase = public_metabase()
    return {
        "connections": public_connections(),
        "dbweb": dbweb,
        "metabase": metabase,
        "status": {
            "raw": stores.ping_engine(stores.raw_engine),
            "dwh": stores.ping_engine(stores.dwh_engine),
            "defect": stores.ping_engine(stores.defect_engine),
            "dbweb": ping_dbweb(dbweb["url"]),
            "metabase": ping_metabase(metabase["url"]),
        },
    }


@router.get("/connections")
def connections_get():
    stores.refresh_pg_engines()
    return ok(_connections_payload())


@router.put("/connections")
def connections_put(body: ConnectionsUpdate, _admin: dict = Depends(require_admin)):
    payload = body.model_dump()
    dbweb_data = payload.pop("dbweb", None)
    metabase_data = payload.pop("metabase", None)
    save_connections(payload)
    if dbweb_data:
        save_dbweb(dbweb_data)
    if metabase_data:
        save_metabase(metabase_data)
    # 连接配置刚变更 → 必须绕过 TTL 立即重建
    stores.refresh_pg_engines(force=True)
    return ok(_connections_payload())


@router.post("/connections/test")
def connections_test(
    body: ConnectionTest, _admin: dict = Depends(require_admin)
):
    stored = public_connections()
    draft = body.model_dump()
    target = draft.pop("target")
    if not str(draft.get("password") or "").strip():
        from app.core.connections import load_connections

        draft["password"] = load_connections()[target]["password"]
    result = ping_parts(draft)
    return ok({"target": target, "label": stored[target]["label"], **result})


@router.post("/connections/dbweb/test")
def connections_dbweb_test(
    body: DbwebTest, _admin: dict = Depends(require_admin)
):
    result = ping_dbweb(body.url)
    return ok({"label": "Adminer 数据浏览", **result})


@router.post("/connections/metabase/test")
def connections_metabase_test(
    body: MetabaseTest, _admin: dict = Depends(require_admin)
):
    result = ping_metabase(body.url, body.username, body.password)
    return ok({"label": "Metabase 数据看板", **result})


@router.get("/metabase/board")
def metabase_board(
    request: Request,
    project_id: str | None = None,
    board: str | None = None,
):
    return ok(
        board_for_project(
            project_id,
            board,
            request_host=(
                request.headers.get("x-forwarded-host") or request.headers.get("host")
            ),
        )
    )
