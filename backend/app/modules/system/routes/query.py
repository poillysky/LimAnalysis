"""system 子路由：ADS 查询与运行时状态。

拆自原 system/router.py。只读查询类接口。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.ads_query import (
    DEFAULT_LIM_HOURS,
    list_query_catalog,
    query_body_cavity,
    query_machine_cavity,
    query_series,
)
from app.core.response import fail, ok
from app.core.runtime_status import build_runtime_status
from app.core.yield_alerts import list_yield_alerts, load_alert_rules, save_alert_rules
from app.modules.system.schemas import CavityAlertRulesIn

router = APIRouter()


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
    hours: int = DEFAULT_LIM_HOURS,
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
    hours: int = DEFAULT_LIM_HOURS,
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
def yield_alerts_api(project_id: str | None = None, hours: int = DEFAULT_LIM_HOURS):
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


@router.get("/runtime-status")
def runtime_status_get():
    try:
        return ok(build_runtime_status())
    except Exception as exc:
        return JSONResponse(fail(str(exc)[:300]), status_code=500)
