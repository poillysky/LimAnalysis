from app.core.db import MetaSession, meta_engine
from app.core.meta_models import (  # noqa: F401
    MetaAggModel,
    MetaAggModelField,
    MetaBase,
    MetaEtlModel,
    MetaEtlModelField,
    MetaJob,
    MetaSetting,
)

SYSTEM_DEFAULTS_KEY = "system_defaults"
AUTH_SECRET_KEY = "auth_secret"
PERSONNEL_OPTIONS_KEY = "personnel_options"
CONNECTIONS_KEY = "external_connections"
DBWEB_KEY = "dbweb_browser"
METABASE_KEY = "metabase_browser"
SFC_CRAWLER_KEY = "sfc_crawler"
AI_MODEL_KEY = "ai_model"
ETL_SCHEDULER_KEY = "etl_scheduler"
AGG_SCHEDULER_KEY = "agg_scheduler"
MACHINE_CATALOG_KEY = "machine_catalog"
DUTY_ROSTER_KEY = "duty_roster"
MANUAL_NOTICES_KEY = "manual_notices"
DEFECT_SCAN_ITEMS_KEY = "defect_scan_items"
CAVITY_ALERT_RULES_KEY = "cavity_alert_rules"
DEFECT_ANALYSIS_ALERT_KEY = "defect_analysis_alert"
INSPECTION_KEY = "inspection"
DISK_CLEANUP_KEY = "disk_cleanup"

DEFAULT_INSPECTION = {
    "mold_root_path": "",
    "appearance_root_path": "",
}

DEFAULT_DISK_CLEANUP = {
    "enabled": True,
    "db_retention_days": 90,
    "image_retention_days": 90,
    "run_hour": 3,
    "last_run_time": "",
    "last_run_status": "",
    "last_run_message": "",
    "last_run_result": {},
}

# 代码只放默认值，不含任何项目名单
DEFAULT_SYSTEM_SETTINGS = {
    "sync": {"interval_minutes": 10, "mode": "full", "retry": 3},
    "unique_key": {"strategy": "sn", "column": "FCoverSN"},
}

DEFAULT_PERSONNEL_OPTIONS = {
    "shifts": ["长白班", "两班倒", "三班倒"],
    "departments": [
        "注塑机调试",
        "注塑机影像",
        "自动化调试",
        "模具钳工",
        "外观线",
        "车间工艺",
        "管理",
    ],
}

DEFAULT_SFC_CRAWLER = {
    "sso_login_url": "http://sso.aac.com/login.aspx",
    "sfc_base_url": "http://sfc-bjm.aac.tech",
    "sfc_logon_path": "/SFCS/LogOn.aspx",
    "sfc_data_path": "/SFCS/Views/GetTableData2.aspx",
    "line_option": "all",
    "section_option": "LIM",
    "crawl_interval": 10,
    "retry": 3,
    "is_active": False,
    "is_running": False,
    "last_run_time": "",
    "last_run_status": "",
}

# OpenAI 兼容接口（可用官方 / 通义 / DeepSeek / 本地 Ollama 等）
DEFAULT_AI_MODEL = {
    "enabled": False,
    "provider": "openai_compatible",
    "base_url": "https://api.openai.com/v1",
    "api_key_enc": "",
    "model": "gpt-4o-mini",
    "timeout_seconds": 45,
    "temperature": 0.2,
}

DEFAULT_ETL_SCHEDULER = {
    "is_active": False,
    "run_interval": 30,
    "last_run_time": "",
    "last_run_status": "",
    "last_run_message": "",
}

DEFAULT_AGG_SCHEDULER = {
    "is_active": False,
    "mode": "hourly",
    "backfill_hours": 12,
    "last_run_time": "",
    "last_run_status": "",
    "last_run_message": "",
}

_MACHINE_SERIES = (("D", 13), ("N", 14), ("M", 12), ("K", 6), ("H", 6), ("I", 6))
DEFAULT_MACHINE_CATALOG = {
    "groups": [
        {
            "name": letter,
            "machines": [f"{letter}{index}" for index in range(1, count + 1)],
        }
        for letter, count in _MACHINE_SERIES
    ]
}


def init_meta_store() -> None:
    MetaBase.metadata.create_all(meta_engine)
    db = MetaSession()
    try:
        if db.get(MetaSetting, SYSTEM_DEFAULTS_KEY) is None:
            db.add(MetaSetting(key=SYSTEM_DEFAULTS_KEY, value=DEFAULT_SYSTEM_SETTINGS))
        if db.get(MetaSetting, AUTH_SECRET_KEY) is None:
            import secrets

            db.add(MetaSetting(key=AUTH_SECRET_KEY, value={"secret": secrets.token_hex(32)}))
        if db.get(MetaSetting, PERSONNEL_OPTIONS_KEY) is None:
            db.add(MetaSetting(key=PERSONNEL_OPTIONS_KEY, value=DEFAULT_PERSONNEL_OPTIONS))
        if db.get(MetaSetting, MACHINE_CATALOG_KEY) is None:
            db.add(MetaSetting(key=MACHINE_CATALOG_KEY, value=DEFAULT_MACHINE_CATALOG))
        if db.get(MetaSetting, DUTY_ROSTER_KEY) is None:
            db.add(MetaSetting(key=DUTY_ROSTER_KEY, value={"entries": []}))
        if db.get(MetaSetting, MANUAL_NOTICES_KEY) is None:
            db.add(MetaSetting(key=MANUAL_NOTICES_KEY, value={"notices": []}))
        if db.get(MetaSetting, DEFECT_SCAN_ITEMS_KEY) is None:
            db.add(MetaSetting(key=DEFECT_SCAN_ITEMS_KEY, value={"projects": {}}))
        if db.get(MetaSetting, INSPECTION_KEY) is None:
            db.add(MetaSetting(key=INSPECTION_KEY, value=DEFAULT_INSPECTION))
        if db.get(MetaSetting, SFC_CRAWLER_KEY) is None:
            db.add(MetaSetting(key=SFC_CRAWLER_KEY, value=DEFAULT_SFC_CRAWLER))
        if db.get(MetaSetting, AI_MODEL_KEY) is None:
            db.add(MetaSetting(key=AI_MODEL_KEY, value=DEFAULT_AI_MODEL))
        if db.get(MetaSetting, ETL_SCHEDULER_KEY) is None:
            db.add(MetaSetting(key=ETL_SCHEDULER_KEY, value=DEFAULT_ETL_SCHEDULER))
        if db.get(MetaSetting, AGG_SCHEDULER_KEY) is None:
            db.add(MetaSetting(key=AGG_SCHEDULER_KEY, value=DEFAULT_AGG_SCHEDULER))
        if db.get(MetaSetting, DISK_CLEANUP_KEY) is None:
            db.add(MetaSetting(key=DISK_CLEANUP_KEY, value=DEFAULT_DISK_CLEANUP))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    from app.core.users import seed_default_admin

    seed_default_admin()
