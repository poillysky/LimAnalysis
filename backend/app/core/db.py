import logging
import threading
import time
from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

_sqlite_file = settings.sqlite_file
_sqlite_file.parent.mkdir(parents=True, exist_ok=True)

_engine_lock = threading.RLock()

# PG engine 重建节流：URL 未变且在 TTL 内直接复用现有连接池
_PG_ENGINE_TTL = 30.0
_pg_engine_key: tuple[str, str, str] | None = None
_pg_engine_at: float = 0.0

meta_engine = create_engine(
    settings.meta_database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

raw_engine = create_engine(
    settings.raw_database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
dwh_engine = create_engine(
    settings.dwh_database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
defect_engine = create_engine(
    settings.defect_database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)


@event.listens_for(meta_engine, "connect")
def _sqlite_wal(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


MetaSession = sessionmaker(bind=meta_engine, autoflush=False, autocommit=False)
RawSession = sessionmaker(bind=raw_engine, autoflush=False, autocommit=False)
DwhSession = sessionmaker(bind=dwh_engine, autoflush=False, autocommit=False)
DefectSession = sessionmaker(bind=defect_engine, autoflush=False, autocommit=False)


def get_meta_db() -> Generator[Session, None, None]:
    db = MetaSession()
    try:
        yield db
    finally:
        db.close()


def ping_engine(engine: Engine) -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def refresh_pg_engines(force: bool = False) -> bool:
    """按连接管理重建 raw/dwh/defect engine；加锁避免与查询/入库并发 dispose。

    带 TTL 缓存：URL 未变且未过期时直接跳过，避免每次查询都重建连接池
    （旧实现无缓存，ETL/聚合/查询路径上每次调用都 create_engine + dispose）。

    :param force: True 时无条件重建（仅用于连接配置真正变更后）。
    :return: 是否真的做了重建。
    """
    global raw_engine, dwh_engine, defect_engine, _pg_engine_key, _pg_engine_at
    from app.core.connections import build_pg_url, load_connections

    with _engine_lock:
        stored = load_connections()
        urls = (
            build_pg_url(stored["raw"]),
            build_pg_url(stored["dwh"]),
            build_pg_url(stored["defect"]),
        )
        now = time.monotonic()
        if not force and _pg_engine_key == urls and (now - _pg_engine_at) < _PG_ENGINE_TTL:
            return False

        old_raw, old_dwh, old_defect = raw_engine, dwh_engine, defect_engine
        next_raw = create_engine(
            urls[0],
            pool_pre_ping=True,
            connect_args={"connect_timeout": 8},
        )
        next_dwh = create_engine(
            urls[1],
            pool_pre_ping=True,
            connect_args={"connect_timeout": 8},
        )
        next_defect = create_engine(
            urls[2],
            pool_pre_ping=True,
            connect_args={"connect_timeout": 8},
        )
        raw_engine = next_raw
        dwh_engine = next_dwh
        defect_engine = next_defect
        RawSession.configure(bind=raw_engine)
        DwhSession.configure(bind=dwh_engine)
        DefectSession.configure(bind=defect_engine)
        _pg_engine_key = urls
        _pg_engine_at = now
        for old in (old_raw, old_dwh, old_defect):
            try:
                old.dispose()
            except Exception:
                logger.debug("dispose old engine failed", exc_info=True)
    return True


# 启动即用 meta 里保存的连接，避免一直打着 .env 里过期的 127.0.0.1
try:
    refresh_pg_engines(force=True)
except Exception:
    logger.warning(
        "启动时刷新 PG 连接失败，先用 .env 默认值；稍后由 /system/connections 或 TTL 重建",
        exc_info=True,
    )
