"""
系统配置工具函数
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def get_cfg_db_path() -> str:
    """获取配置数据库路径"""
    cfg_db_path = os.getenv("CFG_DB_PATH", "ETL/backend/data/etl_config.sqlite")
    
    if not os.path.isabs(cfg_db_path):
        project_root = Path(__file__).parent.parent.parent.parent
        cfg_db_path = str(project_root / cfg_db_path)
    
    return cfg_db_path


def get_system_setting(key: str, default: str = None) -> str:
    """
    从配置数据库读取系统设置
    
    Args:
        key: 参数键
        default: 默认值
        
    Returns:
        参数值，如果不存在则返回默认值
    """
    cfg_db_path = get_cfg_db_path()
    
    # 确保数据库文件存在
    if not os.path.exists(cfg_db_path):
        if default is not None:
            return default
        raise FileNotFoundError(f"配置数据库不存在: {cfg_db_path}")
    
    engine = create_engine(f"sqlite:///{cfg_db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        result = session.execute(
            text("SELECT param_value FROM system_settings WHERE param_key = :key"),
            {"key": key}
        )
        row = result.fetchone()
        
        if row:
            return row[0]
        elif default is not None:
            return default
        else:
            raise ValueError(f"未找到系统设置: {key}")
    finally:
        session.close()
        engine.dispose()


def set_system_setting(key: str, value: str, name: str = None, description: str = None, category: str = "system"):
    """
    设置系统配置
    
    Args:
        key: 参数键
        value: 参数值
        name: 参数名称
        description: 参数描述
        category: 参数分类
    """
    cfg_db_path = get_cfg_db_path()
    
    engine = create_engine(f"sqlite:///{cfg_db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # 检查是否存在
        result = session.execute(
            text("SELECT id FROM system_settings WHERE param_key = :key"),
            {"key": key}
        )
        exists = result.fetchone()
        
        if exists:
            # 更新
            session.execute(
                text("""
                    UPDATE system_settings 
                    SET param_value = :value, updated_at = CURRENT_TIMESTAMP
                    WHERE param_key = :key
                """),
                {"key": key, "value": value}
            )
        else:
            # 插入
            session.execute(
                text("""
                    INSERT INTO system_settings 
                    (param_key, param_value, param_name, description, category, created_at, updated_at)
                    VALUES (:key, :value, :name, :description, :category, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "key": key,
                    "value": value,
                    "name": name or key,
                    "description": description or "",
                    "category": category
                }
            )
        
        session.commit()
    finally:
        session.close()
        engine.dispose()
