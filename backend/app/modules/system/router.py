from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core import db as stores
from app.core.ads_query import (
    list_query_catalog,
    query_body_cavity,
    query_machine_cavity,
    query_series,
)
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
from app.core.db_browser import (
    ensure_engines,
    list_tables,
    table_preview,
    target_info,
)
from app.core.disk_cleanup import (
    request_disk_cleanup,
    save_disk_cleanup_config,
    status_payload,
)
from app.core.duty_roster import (
    create_roster_entry,
    delete_roster_entry,
    list_roster,
    update_roster_entry,
)
from app.core.manual_notices import (
    delete_manual_notice,
    list_manual_notices,
    send_manual_notice,
)
from app.core.metabase_embed import board_for_project
from app.core.personnel import (
    create_person,
    delete_person,
    get_person,
    list_persons,
    load_personnel_options,
    update_person,
)
from app.core.projects import (
    create_project,
    delete_project,
    get_project,
    load_machine_catalog,
    load_projects,
    load_system_defaults,
    save_system_defaults,
    update_project,
)
from app.core.response import fail, ok
from app.core.users import (
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
)
from app.core.yield_alerts import list_yield_alerts, load_alert_rules, save_alert_rules
from app.modules.system.schemas import (
    CavityAlertRulesIn,
    ConnectionsUpdate,
    ConnectionTest,
    DbwebTest,
    DefaultsUpdate,
    DiskCleanupUpdate,
    DutyRosterCreate,
    DutyRosterUpdate,
    ManualNoticeCreate,
    MetabaseTest,
    PersonCreate,
    PersonUpdate,
    ProjectCreate,
    ProjectUpdate,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/system", tags=["system"])


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


@router.get("/connections")
def connections_get():
    stores.refresh_pg_engines()
    dbweb = public_dbweb()
    metabase = public_metabase()
    return ok(
        {
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
    )


@router.put("/connections")
def connections_put(body: ConnectionsUpdate):
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
    dbweb = public_dbweb()
    metabase = public_metabase()
    return ok(
        {
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
    )


@router.post("/connections/test")
def connections_test(body: ConnectionTest):
    stored = public_connections()
    draft = body.model_dump()
    target = draft.pop("target")
    if not str(draft.get("password") or "").strip():
        from app.core.connections import load_connections

        draft["password"] = load_connections()[target]["password"]
    result = ping_parts(draft)
    return ok({"target": target, "label": stored[target]["label"], **result})


@router.post("/connections/dbweb/test")
def connections_dbweb_test(body: DbwebTest):
    result = ping_dbweb(body.url)
    return ok({"label": "Adminer 数据浏览", **result})


@router.post("/connections/metabase/test")
def connections_metabase_test(body: MetabaseTest):
    result = ping_metabase(body.url, body.username, body.password)
    return ok({"label": "Metabase 数据看板", **result})


@router.get("/metabase/board")
def metabase_board(project_id: str | None = None, board: str | None = None):
    return ok(board_for_project(project_id, board))


@router.get("/query/catalog")
def query_catalog(
    project_id: str | None = None,
    line: str | None = None,
    machine: str | None = None,
    cavity: str | None = None,
    core: str | None = None,
):
    try:
        return ok(
            list_query_catalog(
                project_id, line=line, machine=machine, cavity=cavity, core=core
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/query/series")
def query_series_api(
    project_id: str,
    metric: str = "appearance",
    line: str | None = None,
    machine: str | None = None,
    cavity: str | None = None,
    core: str | None = None,
    cavity_letter: str | None = None,
    body_mold: str | None = None,
    body_cavity: str | None = None,
):
    try:
        return ok(
            query_series(
                project_id,
                metric=metric,
                line=line,
                machine=machine,
                cavity=cavity,
                core=core,
                cavity_letter=cavity_letter,
                body_mold=body_mold,
                body_cavity=body_cavity,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/query/machine-cavity")
def query_machine_cavity_api(
    project_id: str,
    hours: int = 3,
    metric: str = "appearance",
    exclude_machine_cavities: str = "",
    exclude_body_cavities: str = "",
):
    try:
        return ok(
            query_machine_cavity(
                project_id,
                hours=hours,
                metric=metric,
                exclude_machine_cavities=exclude_machine_cavities,
                exclude_body_cavities=exclude_body_cavities,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/query/body-cavity")
def query_body_cavity_api(
    project_id: str,
    hours: int = 3,
    metric: str = "appearance",
    exclude_machine_cavities: str = "",
    exclude_body_cavities: str = "",
):
    try:
        return ok(
            query_body_cavity(
                project_id,
                hours=hours,
                metric=metric,
                exclude_machine_cavities=exclude_machine_cavities,
                exclude_body_cavities=exclude_body_cavities,
            )
        )
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/query/yield-alerts")
def yield_alerts_api(project_id: str | None = None, hours: int = 3):
    try:
        return ok(list_yield_alerts(project_id, hours=hours))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/alert-rules")
def alert_rules_get():
    return ok(load_alert_rules())


@router.put("/alert-rules")
def alert_rules_put(body: CavityAlertRulesIn):
    return ok(save_alert_rules(body.model_dump()))


@router.get("/disk-cleanup")
def disk_cleanup_get():
    try:
        return ok(status_payload())
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.put("/disk-cleanup")
def disk_cleanup_put(body: DiskCleanupUpdate):
    try:
        config = save_disk_cleanup_config(body.model_dump(exclude_unset=True))
        return ok({"config": config})
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.post("/disk-cleanup/run")
def disk_cleanup_run():
    result = request_disk_cleanup(trigger="manual")
    if not result.get("accepted"):
        return JSONResponse(fail(result.get("message") or "无法入队"), status_code=409)
    return ok(result)


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
def db_table_rows(target: str, table: str, limit: int = 50, offset: int = 0):
    try:
        ensure_engines(target)
        return ok(table_preview(target, table, limit=limit, offset=offset))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)


@router.get("/defaults")
def get_defaults():
    return ok(load_system_defaults())


@router.put("/defaults")
def put_defaults(body: DefaultsUpdate):
    return ok(save_system_defaults(body.value))


@router.get("/projects")
def list_projects():
    return ok(
        {
            "defaults": load_system_defaults(),
            "projects": load_projects(),
            "machine_catalog": load_machine_catalog(),
        }
    )


@router.post("/projects")
def add_project(body: ProjectCreate):
    try:
        return ok(create_project(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/projects/{project_id}")
def read_project(project_id: str):
    item = get_project(project_id)
    if item is None:
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok(item)


@router.put("/projects/{project_id}")
def edit_project(project_id: str, body: ProjectUpdate):
    item = update_project(project_id, body.model_dump(exclude_unset=True))
    if item is None:
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok(item)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str):
    if not delete_project(project_id):
        return JSONResponse(fail("项目不存在"), status_code=404)
    return ok({"project_id": project_id})


def _user_error(exc: Exception, not_found: bool = False):
    if isinstance(exc, LookupError) or not_found:
        return JSONResponse(fail(str(exc) or "用户不存在"), status_code=404)
    return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/users")
def users_list():
    return ok({"users": list_users()})


@router.post("/users")
def users_add(body: UserCreate):
    try:
        return ok(create_user(body.model_dump()))
    except ValueError as exc:
        code = 409 if "已存在" in str(exc) else 400
        return JSONResponse(fail(str(exc)), status_code=code)


@router.get("/users/{username}")
def users_read(username: str):
    item = get_user(username)
    if item is None:
        return JSONResponse(fail("用户不存在"), status_code=404)
    return ok(item)


@router.put("/users/{username}")
def users_edit(username: str, body: UserUpdate):
    try:
        return ok(update_user(username, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        return _user_error(exc, not_found=True)
    except ValueError as exc:
        return _user_error(exc)


@router.delete("/users/{username}")
def users_remove(username: str):
    try:
        delete_user(username)
        return ok({"username": username})
    except LookupError as exc:
        return _user_error(exc, not_found=True)
    except ValueError as exc:
        return _user_error(exc)


@router.get("/persons")
def persons_list():
    return ok(
        {"persons": list_persons(), "options": load_personnel_options()}
    )


@router.post("/persons")
def persons_add(body: PersonCreate):
    try:
        return ok(create_person(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/persons/{person_id}")
def persons_read(person_id: int):
    item = get_person(person_id)
    if item is None:
        return JSONResponse(fail("人员不存在"), status_code=404)
    return ok(item)


@router.put("/persons/{person_id}")
def persons_edit(person_id: int, body: PersonUpdate):
    try:
        return ok(update_person(person_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/persons/{person_id}")
def persons_remove(person_id: int):
    try:
        delete_person(person_id)
        return ok({"id": person_id})
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)


@router.get("/duty-roster")
def duty_roster_list():
    return ok(list_roster())


@router.post("/duty-roster")
def duty_roster_add(body: DutyRosterCreate):
    try:
        return ok(create_roster_entry(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.put("/duty-roster/{entry_id}")
def duty_roster_edit(entry_id: int, body: DutyRosterUpdate):
    try:
        return ok(
            update_roster_entry(entry_id, body.model_dump(exclude_unset=True))
        )
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/duty-roster/{entry_id}")
def duty_roster_remove(entry_id: int):
    try:
        delete_roster_entry(entry_id)
        return ok({"id": entry_id})
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)


@router.get("/manual-notices")
def manual_notices_list():
    return ok(list_manual_notices())


@router.post("/manual-notices")
def manual_notices_send(body: ManualNoticeCreate):
    try:
        return ok(send_manual_notice(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/manual-notices/{notice_id}")
def manual_notices_remove(notice_id: int):
    try:
        delete_manual_notice(notice_id)
        return ok({"id": notice_id})
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
