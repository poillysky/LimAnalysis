"""
数据库引擎管理
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.settings import settings


# 全局引擎缓存
_cfg_engine: Engine | None = None
_mysql_engine: Engine | None = None  # ✅ 添加 MySQL 引擎缓存


def _get_cfg_db_path() -> str:
    """获取 SQLite 配置数据库路径"""
    db_path = os.getenv("CFG_DB_PATH", settings.cfg_db_path)
    
    # 相对路径转绝对路径
    if not os.path.isabs(db_path):
        project_root = Path(__file__).parent.parent.parent
        db_path = str(project_root / db_path)
    
    # 确保目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    return db_path


def cfg_sqlite_url() -> str:
    """生成 SQLite 配置数据库 URL"""
    db_path = _get_cfg_db_path()
    return f"sqlite:///{db_path}"


def _decrypt_password(encrypted_password: str) -> str:
    """解密密码"""
    from cryptography.fernet import Fernet
    
    cipher = Fernet(settings.encryption_key.encode())
    return cipher.decrypt(encrypted_password.encode()).decode()


def get_cfg_engine() -> Engine:
    """获取 SQLite 配置数据库引擎"""
    global _cfg_engine
    
    if _cfg_engine is None:
        url = cfg_sqlite_url()
        _cfg_engine = create_engine(url, pool_pre_ping=True)
    
    return _cfg_engine


def get_mysql_config_from_db(config_name: str = "default") -> dict:
    """从配置数据库读取 MySQL 配置"""
    engine = get_cfg_engine()
    
    with engine.connect() as conn:
        # 查询指定配置
        result = conn.execute(
            text("""
                SELECT host, port, username, password, database, 
                       max_connections, min_connections, connection_timeout
                FROM mysql_configs
                WHERE name = :name AND is_active = 1
                LIMIT 1
            """),
            {"name": config_name}
        ).fetchone()
        
        # 如果没有，查询任意激活配置
        if not result:
            result = conn.execute(
                text("""
                    SELECT host, port, username, password, database, 
                           max_connections, min_connections, connection_timeout
                    FROM mysql_configs
                    WHERE is_active = 1
                    LIMIT 1
                """)
            ).fetchone()
        
        if not result:
            raise ValueError("未找到激活的 MySQL 配置")
        
        host, port, username, password, database, max_conn, min_conn, timeout = result
        
        # 解密密码
        decrypted_password = _decrypt_password(password)
        
        return {
            "url": f"mysql+pymysql://{username}:{decrypted_password}@{host}:{port}/{database}?charset=utf8mb4",
            "pool_size": min_conn,
            "max_overflow": max_conn - min_conn,
            "pool_timeout": timeout,
            "pool_recycle": 3600,
        }


def get_mysql_engine(config_name: str = "default", force_reload: bool = False) -> Engine:
    """
    获取 MySQL 引擎（使用缓存，避免重复创建连接池）
    
    ✅ 优化：使用全局缓存，避免每次都创建新的连接池
    
    参数：
        config_name: 配置名称
        force_reload: 是否强制重新加载配置（默认 False）
    """
    global _mysql_engine
    
    # 如果已有缓存且不强制重新加载，直接返回
    if _mysql_engine is not None and not force_reload:
        return _mysql_engine
    
    # 读取配置
    config = get_mysql_config_from_db(config_name)
    
    # 如果需要重新创建，先关闭旧引擎
    if _mysql_engine is not None:
        _mysql_engine.dispose()
    
    # 创建新引擎并缓存
    _mysql_engine = create_engine(
        config["url"],
        pool_size=config["pool_size"],
        max_overflow=config["max_overflow"],
        pool_timeout=config["pool_timeout"],
        pool_recycle=config["pool_recycle"],
        pool_pre_ping=True,
        # ✅ 添加连接池回收策略
        pool_reset_on_return='rollback',  # 归还连接时回滚事务
        echo_pool=False,  # 不打印连接池日志
    )
    
    return _mysql_engine


def dispose_mysql_engine():
    """
    释放 MySQL 引擎和连接池
    
    ✅ 用于手动清理连接池
    """
    global _mysql_engine
    
    if _mysql_engine is not None:
        _mysql_engine.dispose()
        _mysql_engine = None
