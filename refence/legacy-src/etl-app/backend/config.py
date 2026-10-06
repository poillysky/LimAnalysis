"""
ETL 配置管理模块

本模块使用 ETL 自己的 SQLite 数据库（ETL/backend/data/etl_config.sqlite）
不依赖 DataLim4 的配置系统
"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class ConfigManager:
    """ETL 配置管理器"""
    
    def __init__(self):
        """初始化配置管理器"""
        self.cfg_db_path = self._get_cfg_db_path()
        self._engine = None
    
    def _get_cfg_db_path(self) -> str:
        """获取配置数据库路径"""
        # 优先使用环境变量，Docker 中使用 /app/data
        cfg_db_path = os.getenv("ETL_CFG_DB_PATH")
        
        print(f"🔍 [DEBUG] ETL_CFG_DB_PATH env = {cfg_db_path}")
        print(f"🔍 [DEBUG] /app/data exists = {os.path.exists('/app/data')}")
        
        if not cfg_db_path:
            # 检测是否在 Docker 环境中
            if os.path.exists("/app/data"):
                cfg_db_path = "/app/data/etl_config.sqlite"
                print(f"🔍 [DEBUG] Using Docker path")
            else:
                # 本地开发环境：使用绝对路径
                print(f"🔍 [DEBUG] __file__ = {__file__}")
                print(f"🔍 [DEBUG] Path(__file__) = {Path(__file__)}")
                print(f"🔍 [DEBUG] Path(__file__).resolve() = {Path(__file__).resolve()}")
                
                # __file__ 的绝对路径
                config_file_path = Path(__file__).resolve()
                # backend 目录
                backend_dir = config_file_path.parent
                # backend/data/etl_config.sqlite
                cfg_db_path = str(backend_dir / "data" / "etl_config.sqlite")
                
                print(f"🔍 [DEBUG] backend_dir = {backend_dir}")
                print(f"🔍 [DEBUG] cfg_db_path = {cfg_db_path}")
        
        # 确保目录存在
        os.makedirs(os.path.dirname(cfg_db_path), exist_ok=True)
        
        print(f"🔍 [CONFIG] 数据库最终路径: {cfg_db_path}")
        
        return cfg_db_path
    
    @property
    def engine(self):
        """获取配置数据库引擎"""
        if self._engine is None:
            self._engine = create_engine(
                f"sqlite:///{self.cfg_db_path}",
                connect_args={"check_same_thread": False}
            )
        return self._engine
    
    def get_session(self):
        """
        获取数据库会话
        
        用法1 - 手动管理:
            session = config_manager.get_session()
            try:
                # 操作
                session.commit()
            finally:
                session.close()
        
        用法2 - 上下文管理器:
            with config_manager.get_session() as session:
                # 操作（自动 commit/rollback/close）
        """
        from contextlib import contextmanager
        
        SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        
        class SessionWrapper:
            """Session 包装器，支持上下文管理器"""
            def __init__(self):
                self._session = SessionLocal()
            
            def __enter__(self):
                return self._session
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    try:
                        self._session.commit()
                    except Exception:
                        self._session.rollback()
                        raise
                else:
                    self._session.rollback()
                
                self._session.close()
                return False
            
            # 代理所有 session 方法
            def __getattr__(self, name):
                return getattr(self._session, name)
        
        return SessionWrapper()
    
    def init_database(self):
        """初始化 ETL 配置表"""
        from backend.models.base import Base
        
        # 创建 ETL 相关的表
        Base.metadata.create_all(self.engine)
        
        # 初始化默认配置
        self._init_default_config()
    
    def _init_default_config(self):
        """初始化默认 ETL 配置"""
        from backend.models.etl_config import ETLConfig
        
        with self.get_session() as session:
            # 检查是否已有配置
            existing_config = session.query(ETLConfig).first()
            if existing_config:
                return
            
            # 创建默认配置
            default_config = ETLConfig(
                name="default",
                description="默认 ETL 配置",
                source_database="sfc_raw",
                target_database="link_db",
                analytics_database="analytics_dw",
                run_interval=60,
                backfill_hours=24,
                timeout=300,
                is_active=True
            )
            
            session.add(default_config)
            # commit 由上下文管理器自动处理
    
    def get_etl_config(self):
        """获取 ETL 全局配置"""
        from backend.models.etl_config import ETLConfig
        from backend.core.logger import CHINA_TZ
        
        with self.get_session() as session:
            config = session.query(ETLConfig).first()
            
            if not config:
                return None
            
            # 处理时区：如果 last_run_time 没有时区信息，添加东八区时区
            last_run_time = config.last_run_time
            if last_run_time and last_run_time.tzinfo is None:
                last_run_time = last_run_time.replace(tzinfo=CHINA_TZ)
            
            return {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "mysql_config_id": config.mysql_config_id,
                "source_database": config.source_database,
                "target_database": config.target_database,
                "analytics_database": config.analytics_database,
                "run_interval": config.run_interval,
                "backfill_hours": config.backfill_hours,
                "timeout": config.timeout,
                "is_active": config.is_active,
                "last_run_time": last_run_time,
                "last_run_status": config.last_run_status
            }
    
    def get_mysql_config(self, config_id: int):
        """
        获取 MySQL 配置
        
        Args:
            config_id: MySQL 配置 ID
            
        Returns:
            MySQL 配置字典
        """
        from backend.models.etl_config import MySQLConfig
        from cryptography.fernet import Fernet
        
        with self.get_session() as session:
            config = session.query(MySQLConfig).filter(MySQLConfig.id == config_id).first()
            
            if not config:
                return None
            
            # 解密密码
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if encryption_key:
                cipher = Fernet(encryption_key.encode())
                password = cipher.decrypt(config.password.encode()).decode()
            else:
                password = config.password
            
            return {
                "id": config.id,
                "name": config.name,
                "host": config.host,
                "port": config.port,
                "username": config.username,
                "password": password,
                "database": config.database,
                "min_connections": config.min_connections,
                "max_connections": config.max_connections,
                "connection_timeout": config.connection_timeout
            }


# 全局配置实例
_config_manager = None


def get_config_manager():
    """获取全局配置管理器实例"""
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager()
    
    return _config_manager


def init_etl_config():
    """初始化 ETL 配置"""
    config_manager = get_config_manager()
    config_manager.init_database()
    return config_manager