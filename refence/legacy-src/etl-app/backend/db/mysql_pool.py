"""
MySQL 连接池管理
"""
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 全局 MySQL 引擎
_mysql_engine = None
_current_config_id = None


def get_mysql_engine(config: dict):
    """
    获取 MySQL 引擎（带连接池）
    
    参数：
        config: MySQL 配置字典
            - host: 主机地址
            - port: 端口号
            - username: 用户名
            - password: 密码（已解密）
            - database: 数据库名
            - min_connections: 最小连接数
            - max_connections: 最大连接数
            - connection_timeout: 连接超时（秒）
    
    返回：
        SQLAlchemy Engine 对象
    """
    global _mysql_engine, _current_config_id
    
    config_id = config.get('id')
    
    # 如果配置 ID 相同且引擎已存在，直接返回
    if _mysql_engine and _current_config_id == config_id:
        return _mysql_engine
    
    # 关闭旧引擎
    if _mysql_engine:
        logger.info(f"关闭旧的 MySQL 连接池（配置 ID: {_current_config_id}）")
        _mysql_engine.dispose()
    
    # 构建连接 URL
    url = (
        f"mysql+pymysql://{config['username']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
        f"?charset=utf8mb4"
    )
    
    # 创建新引擎
    _mysql_engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=config.get('min_connections', 5),
        max_overflow=config.get('max_connections', 20) - config.get('min_connections', 5),
        pool_timeout=config.get('connection_timeout', 30),
        pool_recycle=3600,  # 1小时回收连接
        pool_pre_ping=True,  # 连接前检查
        echo=False
    )
    
    _current_config_id = config_id
    
    logger.info(
        f"创建 MySQL 连接池成功 "
        f"(配置 ID: {config_id}, "
        f"主机: {config['host']}:{config['port']}, "
        f"数据库: {config['database']}, "
        f"连接池: {config.get('min_connections', 5)}-{config.get('max_connections', 20)})"
    )
    
    return _mysql_engine


def reset_mysql_engine():
    """重置 MySQL 引擎（强制重新创建）"""
    global _mysql_engine, _current_config_id
    
    if _mysql_engine:
        logger.info(f"重置 MySQL 连接池（配置 ID: {_current_config_id}）")
        _mysql_engine.dispose()
        _mysql_engine = None
        _current_config_id = None


def test_mysql_connection(config: dict) -> tuple[bool, str]:
    """
    测试 MySQL 连接
    
    参数：
        config: MySQL 配置字典
    
    返回：
        (是否成功, 消息)
    """
    try:
        # 构建连接 URL
        url = (
            f"mysql+pymysql://{config['username']}:{config['password']}"
            f"@{config['host']}:{config['port']}/{config['database']}"
            f"?charset=utf8mb4&connect_timeout={config.get('connection_timeout', 30)}"
        )
        
        # 创建临时引擎
        engine = create_engine(url, pool_pre_ping=True)
        
        # 测试连接
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        
        engine.dispose()
        
        return True, "连接成功"
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"MySQL 连接测试失败: {error_msg}")
        return False, f"连接失败: {error_msg}"
