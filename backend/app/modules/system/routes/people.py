"""system 子路由：人员类主数据。

含用户（列表任意登录可读，增删改需管理员）、人员、值班表、手工通知。
拆自原 system/router.py。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_admin
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
from app.core.personnel import (
    create_person,
    delete_person,
    get_person,
    list_persons,
    load_personnel_options,
    update_person,
)
from app.core.response import fail, ok
from app.core.users import (
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
)
from app.modules.system.schemas import (
    DutyRosterCreate,
    DutyRosterUpdate,
    ManualNoticeCreate,
    PersonCreate,
    PersonUpdate,
    UserCreate,
    UserUpdate,
)

router = APIRouter()


def _user_error(exc: Exception, not_found: bool = False):
    if isinstance(exc, LookupError) or not_found:
        return JSONResponse(fail(str(exc) or "用户不存在"), status_code=404)
    return JSONResponse(fail(str(exc)), status_code=400)


@router.get("/users")
def users_list():
    """任意登录用户可查看；增删改仍需管理员。"""
    return ok({"users": list_users()})


@router.post("/users")
def users_add(body: UserCreate, _admin: dict = Depends(require_admin)):
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
def users_edit(username: str, body: UserUpdate, _admin: dict = Depends(require_admin)):
    try:
        return ok(update_user(username, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        return _user_error(exc, not_found=True)
    except ValueError as exc:
        return _user_error(exc)


@router.delete("/users/{username}")
def users_remove(username: str, _admin: dict = Depends(require_admin)):
    try:
        delete_user(username)
        return ok({"username": username})
    except LookupError as exc:
        return _user_error(exc, not_found=True)
    except ValueError as exc:
        return _user_error(exc)


@router.get("/persons")
def persons_list():
    return ok({"persons": list_persons(), "options": load_personnel_options()})


@router.post("/persons")
def persons_add(body: PersonCreate, _admin: dict = Depends(require_admin)):
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
def persons_edit(
    person_id: int, body: PersonUpdate, _admin: dict = Depends(require_admin)
):
    try:
        return ok(update_person(person_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/persons/{person_id}")
def persons_remove(person_id: int, _admin: dict = Depends(require_admin)):
    try:
        delete_person(person_id)
        return ok({"id": person_id})
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)


@router.get("/duty-roster")
def duty_roster_list():
    return ok(list_roster())


@router.post("/duty-roster")
def duty_roster_add(
    body: DutyRosterCreate, _admin: dict = Depends(require_admin)
):
    try:
        return ok(create_roster_entry(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.put("/duty-roster/{entry_id}")
def duty_roster_edit(
    entry_id: int, body: DutyRosterUpdate, _admin: dict = Depends(require_admin)
):
    try:
        return ok(update_roster_entry(entry_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/duty-roster/{entry_id}")
def duty_roster_remove(entry_id: int, _admin: dict = Depends(require_admin)):
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
    """任意登录用户可发通知；删除需管理员。"""
    try:
        return ok(send_manual_notice(body.model_dump()))
    except ValueError as exc:
        return JSONResponse(fail(str(exc)), status_code=400)


@router.delete("/manual-notices/{notice_id}")
def manual_notices_remove(
    notice_id: int, _admin: dict = Depends(require_admin)
):
    try:
        delete_manual_notice(notice_id)
        return ok({"id": notice_id})
    except LookupError as exc:
        return JSONResponse(fail(str(exc)), status_code=404)
