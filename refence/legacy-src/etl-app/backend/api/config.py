"""
ETL 配置管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from backend.config import get_config_manager
from backend.models.etl_config import ETLConfig, MySQLConfig

router = APIRouter()


class ETLConfigResponse(BaseModel):
    """ETL 配置响应"""
    id: int
    name: str
    description: Optional[str]
    mysql_config_id: Optional[int]
    mysql_config_name: Optional[str]
    source_database: str
    target_database: str
    analytics_database: str
    run_interval: int
    backfill_hours: int
    timeout: int
    is_active: bool
    last_run_time: Optional[datetime]
    last_run_status: Optional[str]


class MySQLConfigResponse(BaseModel):
    """MySQL 配置响应"""
    id: int
    name: str
    description: Optional[str]
    host: str
    port: int
    username: str
    database: str
    min_connections: int
    max_connections: int
    connection_timeout: int
    is_active: bool


class ToggleActiveRequest(BaseModel):
    """切换启用状态请求"""
    is_active: bool


@router.get("/config")
async def get_etl_config():
    """获取 ETL 配置"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(ETLConfig).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="未找到 ETL 配置")
            
            # 获取 MySQL 配置名称
            mysql_config_name = None
            if config.mysql_config_id:
                mysql_config = session.query(MySQLConfig).filter(
                    MySQLConfig.id == config.mysql_config_id
                ).first()
                if mysql_config:
                    mysql_config_name = mysql_config.name
            
            # 格式化时间为东八区时间字符串
            last_run_time_str = None
            if config.last_run_time:
                # 如果时间有时区信息，直接格式化
                if config.last_run_time.tzinfo:
                    last_run_time_str = config.last_run_time.isoformat()
                else:
                    # 如果没有时区信息，添加东八区时区
                    from backend.core.logger import CHINA_TZ
                    last_run_time_with_tz = config.last_run_time.replace(tzinfo=CHINA_TZ)
                    last_run_time_str = last_run_time_with_tz.isoformat()
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "id": config.id,
                    "name": config.name,
                    "description": config.description,
                    "mysql_config_id": config.mysql_config_id,
                    "mysql_config_name": mysql_config_name,
                    "source_database": config.source_database,
                    "target_database": config.target_database,
                    "analytics_database": config.analytics_database,
                    "run_interval": config.run_interval,
                    "backfill_hours": config.backfill_hours,
                    "timeout": config.timeout,
                    "is_active": config.is_active,
                    "last_run_time": last_run_time_str,
                    "last_run_status": config.last_run_status
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mysql-configs")
async def get_mysql_configs():
    """获取所有 MySQL 配置列表"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            configs = session.query(MySQLConfig).filter(MySQLConfig.is_active == True).all()
            
            return {
                "code": 0,
                "message": "success",
                "data": [{
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "host": c.host,
                    "port": c.port,
                    "username": c.username,
                    "database": c.database,
                    "min_connections": c.min_connections,
                    "max_connections": c.max_connections,
                    "connection_timeout": c.connection_timeout,
                    "is_active": c.is_active
                } for c in configs]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/databases")
async def get_databases(mysql_config_id: int):
    """获取指定 MySQL 配置的数据库列表"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            # 获取 MySQL 配置
            mysql_config = session.query(MySQLConfig).filter(
                MySQLConfig.id == mysql_config_id
            ).first()
            
            if not mysql_config:
                raise HTTPException(status_code=404, detail="MySQL 配置不存在")
            
            # 解密密码（假设有加密）
            from cryptography.fernet import Fernet
            import os
            
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if encryption_key:
                cipher = Fernet(encryption_key.encode())
                password = cipher.decrypt(mysql_config.password.encode()).decode()
            else:
                password = mysql_config.password
            
            # 构建连接配置
            from backend.db.mysql_pool import get_mysql_engine
            from sqlalchemy import text
            
            config = {
                'id': mysql_config.id,
                'host': mysql_config.host,
                'port': mysql_config.port,
                'username': mysql_config.username,
                'password': password,
                'database': 'information_schema',  # 连接到系统数据库
                'min_connections': mysql_config.min_connections,
                'max_connections': mysql_config.max_connections,
                'connection_timeout': mysql_config.connection_timeout
            }
            
            # 获取数据库引擎
            engine = get_mysql_engine(config)
            
            try:
                # 查询数据库列表
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT SCHEMA_NAME 
                        FROM information_schema.SCHEMATA 
                        WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                        ORDER BY SCHEMA_NAME
                    """))
                    databases = [row[0] for row in result]
            finally:
                # 如果不是全局引擎，需要释放
                # 由于使用了全局单例，这里不需要dispose
                pass
            
            return {
                "code": 0,
                "message": "success",
                "data": databases
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据库列表失败: {str(e)}")


@router.get("/databases/{database}/tables")
async def get_database_tables(database: str):
    """获取指定数据库的表列表"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            # 获取 ETL 配置中的 MySQL 配置
            etl_config = session.query(ETLConfig).first()
            
            if not etl_config or not etl_config.mysql_config_id:
                raise HTTPException(status_code=404, detail="未配置 MySQL 连接")
            
            # 获取 MySQL 配置
            mysql_config = session.query(MySQLConfig).filter(
                MySQLConfig.id == etl_config.mysql_config_id
            ).first()
            
            if not mysql_config:
                raise HTTPException(status_code=404, detail="MySQL 配置不存在")
            
            # 解密密码
            from cryptography.fernet import Fernet
            import os
            
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if encryption_key:
                cipher = Fernet(encryption_key.encode())
                password = cipher.decrypt(mysql_config.password.encode()).decode()
            else:
                password = mysql_config.password
            
            # 构建连接配置
            from backend.db.mysql_pool import get_mysql_engine
            from sqlalchemy import text
            
            config = {
                'id': mysql_config.id,
                'host': mysql_config.host,
                'port': mysql_config.port,
                'username': mysql_config.username,
                'password': password,
                'database': database,
                'min_connections': mysql_config.min_connections,
                'max_connections': mysql_config.max_connections,
                'connection_timeout': mysql_config.connection_timeout
            }
            
            # 获取数据库引擎
            engine = get_mysql_engine(config)
            
            try:
                # 查询表列表
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT TABLE_NAME 
                        FROM information_schema.TABLES 
                        WHERE TABLE_SCHEMA = :database
                        AND TABLE_TYPE = 'BASE TABLE'
                        ORDER BY TABLE_NAME
                    """), {"database": database})
                    tables = [row[0] for row in result]
            finally:
                # 由于使用了全局单例，这里不需要dispose
                pass
            
            return {
                "code": 0,
                "message": "success",
                "data": tables
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取表列表失败: {str(e)}")


@router.put("/config/toggle-active")
async def toggle_etl_active(request: ToggleActiveRequest):
    """切换 ETL 自动运行状态"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(ETLConfig).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="未找到 ETL 配置")
            
            # 更新状态
            config.is_active = request.is_active
            session.commit()
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "is_active": config.is_active
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_etl_config(config_data: dict):
    """更新 ETL 配置"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(ETLConfig).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="未找到 ETL 配置")
            
            # 更新配置
            if 'mysql_config_id' in config_data:
                config.mysql_config_id = config_data['mysql_config_id']
            if 'source_database' in config_data:
                config.source_database = config_data['source_database']
            if 'target_database' in config_data:
                config.target_database = config_data['target_database']
            if 'analytics_database' in config_data:
                config.analytics_database = config_data['analytics_database']
            if 'run_interval' in config_data:
                config.run_interval = config_data['run_interval']
            if 'backfill_hours' in config_data:
                config.backfill_hours = config_data['backfill_hours']
            if 'timeout' in config_data:
                config.timeout = config_data['timeout']
            
            session.commit()
            
            # 获取 MySQL 配置名称
            mysql_config_name = None
            if config.mysql_config_id:
                mysql_config = session.query(MySQLConfig).filter(
                    MySQLConfig.id == config.mysql_config_id
                ).first()
                if mysql_config:
                    mysql_config_name = mysql_config.name
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "id": config.id,
                    "name": config.name,
                    "description": config.description,
                    "mysql_config_id": config.mysql_config_id,
                    "mysql_config_name": mysql_config_name,
                    "source_database": config.source_database,
                    "target_database": config.target_database,
                    "analytics_database": config.analytics_database,
                    "run_interval": config.run_interval,
                    "backfill_hours": config.backfill_hours,
                    "timeout": config.timeout,
                    "is_active": config.is_active,
                    "last_run_time": config.last_run_time,
                    "last_run_status": config.last_run_status
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mysql-configs")
async def create_mysql_config(config_data: dict):
    """创建 MySQL 配置"""
    try:
        config_manager = get_config_manager()
        
        # 加密密码
        from cryptography.fernet import Fernet
        import os
        
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            raise HTTPException(status_code=500, detail="未配置加密密钥")
        
        cipher = Fernet(encryption_key.encode())
        encrypted_password = cipher.encrypt(config_data['password'].encode()).decode()
        
        with config_manager.get_session() as session:
            # 创建新配置
            new_config = MySQLConfig(
                name=config_data['name'],
                description=config_data.get('description', ''),
                host=config_data['host'],
                port=config_data['port'],
                username=config_data['username'],
                password=encrypted_password,
                database=config_data['database'],
                min_connections=config_data.get('min_connections', 5),
                max_connections=config_data.get('max_connections', 20),
                connection_timeout=config_data.get('connection_timeout', 30),
                is_active=True
            )
            
            session.add(new_config)
            session.flush()  # 刷新以获取 ID，commit 由上下文管理器处理
            
            result = {
                "code": 0,
                "message": "success",
                "data": {
                    "id": new_config.id,
                    "name": new_config.name,
                    "description": new_config.description,
                    "host": new_config.host,
                    "port": new_config.port,
                    "username": new_config.username,
                    "database": new_config.database,
                    "min_connections": new_config.min_connections,
                    "max_connections": new_config.max_connections,
                    "connection_timeout": new_config.connection_timeout,
                    "is_active": new_config.is_active
                }
            }
            
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/mysql-configs/{config_id}")
async def update_mysql_config(config_id: int, config_data: dict):
    """更新 MySQL 配置"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(MySQLConfig).filter(MySQLConfig.id == config_id).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="MySQL 配置不存在")
            
            # 更新字段
            if 'name' in config_data:
                config.name = config_data['name']
            if 'description' in config_data:
                config.description = config_data['description']
            if 'host' in config_data:
                config.host = config_data['host']
            if 'port' in config_data:
                config.port = config_data['port']
            if 'username' in config_data:
                config.username = config_data['username']
            if 'database' in config_data:
                config.database = config_data['database']
            if 'min_connections' in config_data:
                config.min_connections = config_data['min_connections']
            if 'max_connections' in config_data:
                config.max_connections = config_data['max_connections']
            if 'connection_timeout' in config_data:
                config.connection_timeout = config_data['connection_timeout']
            
            # 如果提供了新密码，加密并更新
            if 'password' in config_data and config_data['password']:
                from cryptography.fernet import Fernet
                import os
                
                encryption_key = os.getenv("ENCRYPTION_KEY")
                if not encryption_key:
                    raise HTTPException(status_code=500, detail="未配置加密密钥")
                
                cipher = Fernet(encryption_key.encode())
                config.password = cipher.encrypt(config_data['password'].encode()).decode()
            
            session.commit()
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "id": config.id,
                    "name": config.name,
                    "description": config.description,
                    "host": config.host,
                    "port": config.port,
                    "username": config.username,
                    "database": config.database,
                    "min_connections": config.min_connections,
                    "max_connections": config.max_connections,
                    "connection_timeout": config.connection_timeout,
                    "is_active": config.is_active
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/mysql-configs/{config_id}")
async def delete_mysql_config(config_id: int, force: bool = False):
    """
    删除 MySQL 配置
    
    Args:
        config_id: 配置 ID
        force: 是否强制删除（自动解除 ETL 配置的关联）
    """
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(MySQLConfig).filter(MySQLConfig.id == config_id).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="MySQL 配置不存在")
            
            # 检查是否被 ETL 配置使用
            etl_configs = session.query(ETLConfig).filter(
                ETLConfig.mysql_config_id == config_id
            ).all()
            
            if etl_configs:
                if not force:
                    # 返回详细的使用信息
                    etl_names = [ec.name for ec in etl_configs]
                    raise HTTPException(
                        status_code=400, 
                        detail=f"该配置正在被以下 ETL 配置使用：{', '.join(etl_names)}。请先在 ETL 配置中切换到其他 MySQL 配置，或使用强制删除。"
                    )
                else:
                    # 强制删除：解除所有 ETL 配置的关联
                    for etl_config in etl_configs:
                        etl_config.mysql_config_id = None
                    session.flush()
            
            session.delete(config)
            session.commit()
            
            return {
                "code": 0,
                "message": "success",
                "data": None
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post("/mysql-configs/{config_id}/test")
async def test_mysql_config(config_id: int):
    """测试 MySQL 连接"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            config = session.query(MySQLConfig).filter(MySQLConfig.id == config_id).first()
            
            if not config:
                raise HTTPException(status_code=404, detail="MySQL 配置不存在")
            
            # 解密密码
            from cryptography.fernet import Fernet
            import os
            
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if not encryption_key:
                raise HTTPException(status_code=500, detail="未配置加密密钥")
            
            cipher = Fernet(encryption_key.encode())
            password = cipher.decrypt(config.password.encode()).decode()
            
            # 测试连接
            from backend.db.mysql_pool import test_mysql_connection
            
            test_config = {
                'host': config.host,
                'port': config.port,
                'username': config.username,
                'password': password,
                'database': config.database,
                'connection_timeout': config.connection_timeout
            }
            
            success, message = test_mysql_connection(test_config)
            
            if success:
                return {
                    "code": 0,
                    "message": "连接成功",
                    "data": {"success": True, "message": message}
                }
            else:
                return {
                    "code": 1,
                    "message": "连接失败",
                    "data": {"success": False, "message": message}
                }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.post("/mysql-configs/test-connection")
async def test_mysql_connection_direct(config_data: dict):
    """测试 MySQL 连接（直接测试，无需保存）"""
    try:
        # 测试连接
        from backend.db.mysql_pool import test_mysql_connection
        
        test_config = {
            'host': config_data.get('host'),
            'port': config_data.get('port', 3306),
            'username': config_data.get('username'),
            'password': config_data.get('password'),
            'database': config_data.get('database'),
            'connection_timeout': config_data.get('connection_timeout', 30)
        }
        
        # 验证必填字段
        if not all([test_config['host'], test_config['username'], test_config['password'], test_config['database']]):
            raise HTTPException(status_code=400, detail="请填写完整的连接信息")
        
        success, message = test_mysql_connection(test_config)
        
        if success:
            return {
                "code": 0,
                "message": "连接成功",
                "data": {"success": True, "message": message}
            }
        else:
            return {
                "code": 1,
                "message": "连接失败",
                "data": {"success": False, "message": message}
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")
