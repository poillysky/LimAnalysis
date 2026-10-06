import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.db import MetaSession
from app.core.meta_init import CONNECTIONS_KEY, DBWEB_KEY, METABASE_KEY, init_meta_store
from app.core.meta_models import MetaSetting

TARGETS = ("raw", "dwh", "defect")
LABELS = {"raw": "原始数据库", "dwh": "ETL数据库", "defect": "次品数据库"}
DEFAULT_DBWEB = {
    "url": "http://127.0.0.1:18080",
    "sqlite_path": "/data/meta/lim_meta.sqlite",
}
DEFAULT_METABASE = {
    "url": "http://127.0.0.1:13000",
    "username": "",
    "password": "",
}


def _session():
    init_meta_store()
    return MetaSession()


def _parts_from_url(url: str) -> dict:
    parsed = make_url(url)
    return {
        "host": parsed.host or "127.0.0.1",
        "port": int(parsed.port or 5432),
        "database": parsed.database or "",
        "username": parsed.username or "",
        "password": parsed.password or "",
    }


def _default_store() -> dict:
    return {
        "raw": _parts_from_url(settings.raw_database_url),
        "dwh": _parts_from_url(settings.dwh_database_url),
        "defect": _parts_from_url(settings.defect_database_url),
    }


def _clean_parts(raw, fallback: dict | None = None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    base = dict(fallback or {})
    port = src.get("port", base.get("port") or 5432)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 5432
    password = src.get("password")
    if password is None or str(password) == "":
        password = base.get("password") or ""
    return {
        "host": str(src.get("host") or base.get("host") or "127.0.0.1").strip() or "127.0.0.1",
        "port": port if 1 <= port <= 65535 else 5432,
        "database": str(src.get("database") or base.get("database") or "").strip(),
        "username": str(src.get("username") or base.get("username") or "").strip(),
        "password": str(password),
    }


def load_connections() -> dict:
    defaults = _default_store()
    db = _session()
    try:
        row = db.get(MetaSetting, CONNECTIONS_KEY)
        if row is None or not isinstance(row.value, dict):
            db.add(MetaSetting(key=CONNECTIONS_KEY, value=defaults))
            db.commit()
            stored = defaults
        else:
            stored = {
                "raw": _clean_parts(row.value.get("raw"), defaults["raw"]),
                "dwh": _clean_parts(row.value.get("dwh"), defaults["dwh"]),
                "defect": _clean_parts(row.value.get("defect"), defaults["defect"]),
            }
            if "defect" not in row.value:
                row.value = stored
                flag_modified(row, "value")
                db.commit()
            return stored
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_connections(data: dict) -> dict:
    current = load_connections()
    stored = {
        "raw": _clean_parts(data.get("raw"), current["raw"]),
        "dwh": _clean_parts(data.get("dwh"), current["dwh"]),
        "defect": _clean_parts(data.get("defect"), current["defect"]),
    }
    db = _session()
    try:
        row = db.get(MetaSetting, CONNECTIONS_KEY)
        if row is None:
            db.add(MetaSetting(key=CONNECTIONS_KEY, value=stored))
        else:
            row.value = stored
        db.commit()
        return stored
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def public_connections() -> dict:
    stored = load_connections()
    result = {}
    for key in TARGETS:
        item = stored[key]
        result[key] = {
            "key": key,
            "label": LABELS[key],
            "host": item["host"],
            "port": item["port"],
            "database": item["database"],
            "username": item["username"],
            "password_set": bool(item["password"]),
        }
    return result


def build_pg_url(parts: dict) -> str:
    user = quote(str(parts.get("username") or ""), safe="")
    password = quote(str(parts.get("password") or ""), safe="")
    host = parts.get("host") or "127.0.0.1"
    port = int(parts.get("port") or 5432)
    database = parts.get("database") or ""
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


def ping_parts(parts: dict) -> dict:
    engine = create_engine(
        build_pg_url(parts),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        engine.dispose()


def _clean_dbweb(raw, fallback: dict | None = None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    base = dict(fallback or DEFAULT_DBWEB)
    url = str(src.get("url") or base.get("url") or DEFAULT_DBWEB["url"]).strip()
    sqlite_path = str(
        src.get("sqlite_path") or base.get("sqlite_path") or DEFAULT_DBWEB["sqlite_path"]
    ).strip()
    if not url:
        url = DEFAULT_DBWEB["url"]
    if not sqlite_path:
        sqlite_path = DEFAULT_DBWEB["sqlite_path"]
    return {"url": url.rstrip("/"), "sqlite_path": sqlite_path}


def load_dbweb() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, DBWEB_KEY)
        if row is None or not isinstance(row.value, dict):
            stored = dict(DEFAULT_DBWEB)
            db.add(MetaSetting(key=DBWEB_KEY, value=stored))
            db.commit()
            return stored
        return _clean_dbweb(row.value, DEFAULT_DBWEB)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_dbweb(data: dict) -> dict:
    stored = _clean_dbweb(data, load_dbweb())
    db = _session()
    try:
        row = db.get(MetaSetting, DBWEB_KEY)
        if row is None:
            db.add(MetaSetting(key=DBWEB_KEY, value=stored))
        else:
            row.value = stored
        db.commit()
        return stored
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def public_dbweb() -> dict:
    item = load_dbweb()
    return {
        "url": item["url"],
        "sqlite_path": item["sqlite_path"],
        "label": "Adminer 数据浏览",
    }


def ping_dbweb(url: str | None = None) -> dict:
    target = str(url or load_dbweb()["url"] or "").strip().rstrip("/")
    if not target:
        return {"ok": False, "error": "未配置 Adminer 地址", "url": ""}
    try:
        req = Request(target + "/", method="GET", headers={"User-Agent": "LimAnalysis"})
        with urlopen(req, timeout=3) as resp:
            code = getattr(resp, "status", 200) or 200
        return {"ok": 200 <= int(code) < 500, "error": None, "url": target}
    except HTTPError as exc:
        # Adminer 登录页也可能非 2xx，4xx 仍视为服务已起来
        ok = 400 <= int(exc.code) < 500
        return {
            "ok": ok,
            "error": None if ok else f"HTTP {exc.code}",
            "url": target,
        }
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason or exc)[:200], "url": target}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": target}


def _clean_metabase(raw, fallback: dict | None = None) -> dict:
    src = raw if isinstance(raw, dict) else {}
    base = dict(fallback or DEFAULT_METABASE)
    url = str(src.get("url") or base.get("url") or DEFAULT_METABASE["url"]).strip()
    if not url:
        url = DEFAULT_METABASE["url"]
    username = str(src.get("username") if src.get("username") is not None else base.get("username") or "").strip()
    password = src.get("password")
    if password is None or str(password) == "":
        password = base.get("password") or ""
    return {
        "url": url.rstrip("/"),
        "username": username,
        "password": str(password),
    }


def load_metabase() -> dict:
    db = _session()
    try:
        row = db.get(MetaSetting, METABASE_KEY)
        if row is None or not isinstance(row.value, dict):
            stored = dict(DEFAULT_METABASE)
            db.add(MetaSetting(key=METABASE_KEY, value=stored))
            db.commit()
            return stored
        return _clean_metabase(row.value, DEFAULT_METABASE)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_metabase(data: dict) -> dict:
    stored = _clean_metabase(data, load_metabase())
    db = _session()
    try:
        row = db.get(MetaSetting, METABASE_KEY)
        if row is None:
            db.add(MetaSetting(key=METABASE_KEY, value=stored))
        else:
            row.value = stored
            flag_modified(row, "value")
        db.commit()
        return stored
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def public_metabase() -> dict:
    item = load_metabase()
    return {
        "url": item["url"],
        "username": item.get("username") or "",
        "password_set": bool(item.get("password")),
        "label": "Metabase 数据看板",
    }


def ping_metabase(
    url: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict:
    stored = load_metabase()
    target = str(url or stored.get("url") or "").strip().rstrip("/")
    user = str(username if username not in (None, "") else stored.get("username") or "").strip()
    pwd = str(password or "")
    if not pwd:
        pwd = str(stored.get("password") or "")
    if not target:
        return {"ok": False, "error": "未配置 Metabase 地址", "url": ""}
    health = _ping_metabase_health(target)
    if not health["ok"]:
        return health
    if not user:
        return {"ok": False, "error": "未配置 Metabase 账号", "url": target}
    if not pwd:
        return {"ok": False, "error": "未配置 Metabase 密码", "url": target}
    return _ping_metabase_login(target, user, pwd)


def _ping_metabase_health(target: str) -> dict:
    try:
        req = Request(
            target + "/api/health",
            method="GET",
            headers={"User-Agent": "LimAnalysis"},
        )
        with urlopen(req, timeout=5) as resp:
            code = getattr(resp, "status", 200) or 200
        return {"ok": 200 <= int(code) < 500, "error": None, "url": target}
    except HTTPError as exc:
        ok = 200 <= int(exc.code) < 500
        return {
            "ok": ok,
            "error": None if ok else f"HTTP {exc.code}",
            "url": target,
        }
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason or exc)[:200], "url": target}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": target}


def _ping_metabase_login(target: str, username: str, password: str) -> dict:
    payload = json.dumps({"username": username, "password": password}).encode()
    try:
        req = Request(
            target + "/api/session",
            data=payload,
            method="POST",
            headers={
                "User-Agent": "LimAnalysis",
                "Content-Type": "application/json",
            },
        )
        with urlopen(req, timeout=8) as resp:
            raw = resp.read().decode()
            body = json.loads(raw) if raw else {}
        token = str(body.get("id") or "")
        if not token:
            return {"ok": False, "error": "登录未返回会话", "url": target}
        try:
            logout = Request(
                target + "/api/session",
                method="DELETE",
                headers={
                    "User-Agent": "LimAnalysis",
                    "X-Metabase-Session": token,
                },
            )
            urlopen(logout, timeout=5).read()
        except Exception:
            pass
        return {"ok": True, "error": None, "url": target}
    except HTTPError as exc:
        if int(exc.code) in {401, 400}:
            return {"ok": False, "error": "账号或密码不正确", "url": target}
        return {"ok": False, "error": f"HTTP {exc.code}", "url": target}
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason or exc)[:200], "url": target}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "url": target}
