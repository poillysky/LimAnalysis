"""
数据库工具函数
"""
from typing import Optional, Dict, Any
from sqlalchemy import create_engine, Engine


def encrypt_password(password: str, encryption_key: str) -> str:
    """
    加密密码
    
    Args:
        password: 明文密码
        encryption_key: 加密密钥
        
    Returns:
        加密后的密码
    """
    try:
        from cryptography.fernet import Fernet
        cipher = Fernet(encryption_key.encode())
        encrypted = cipher.encrypt(password.encode())
        return encrypted.decode()
    except ImportError:
        # 如果没有安装 cryptography，使用简单的 base64 编码
        import base64
        encoded = base64.b64encode(password.encode()).decode()
        return encoded


def decrypt_password(encrypted_password: str, encryption_key: str) -> str:
    """
    解密密码
    
    Args:
        encrypted_password: 加密的密码
        encryption_key: 加密密钥
        
    Returns:
        明文密码
    """
    try:
        from cryptography.fernet import Fernet
        cipher = Fernet(encryption_key.encode())
        decrypted = cipher.decrypt(encrypted_password.encode())
        return decrypted.decode()
    except ImportError:
        # 如果没有安装 cryptography，使用简单的 base64 解码
        import base64
        decoded = base64.b64decode(encrypted_password.encode()).decode()
        return decoded
    except Exception:
        # 解密失败，返回原始值
        return encrypted_password


def get_mysql_engine(config: Dict[str, Any]) -> Engine:
    """
    创建 MySQL 数据库引擎
    
    Args:
        config: MySQL 配置字典
        
    Returns:
        SQLAlchemy 引擎
    """
    # 构建连接 URL
    url = f"mysql+pymysql://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?charset={config.get('charset', 'utf8mb4')}"
    
    # 创建引擎
    engine = create_engine(
        url,
        pool_size=config.get('pool_size', 5),
        max_overflow=config.get('max_overflow', 15),
        pool_timeout=config.get('pool_timeout', 30),
        pool_recycle=config.get('pool_recycle', 3600),
        pool_pre_ping=True,
        echo=False
    )
    
    return engine


def test_mysql_connection(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    测试 MySQL 连接
    
    Args:
        config: MySQL 配置字典
        
    Returns:
        测试结果字典
    """
    try:
        engine = get_mysql_engine(config)
        
        # 测试连接
        with engine.connect() as conn:
            result = conn.execute("SELECT 1 as test").fetchone()
            
        return {
            "success": True,
            "message": "连接成功",
            "test_result": result[0] if result else None
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"连接失败: {str(e)}",
            "test_result": None
        }


def get_table_fields(engine: Engine, database: str, table: str) -> list:
    """
    获取表字段信息
    
    Args:
        engine: 数据库引擎
        database: 数据库名
        table: 表名
        
    Returns:
        字段信息列表
    """
    try:
        with engine.connect() as conn:
            sql = f"""
                SELECT 
                    COLUMN_NAME as field_name,
                    DATA_TYPE as field_type,
                    IS_NULLABLE as nullable,
                    COLUMN_DEFAULT as default_value,
                    COLUMN_COMMENT as comment
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = '{database}' 
                AND TABLE_NAME = '{table}'
                ORDER BY ORDINAL_POSITION
            """
            
            result = conn.execute(sql)
            fields = []
            
            for row in result:
                fields.append({
                    "field_name": row.field_name,
                    "field_type": row.field_type,
                    "nullable": row.nullable == "YES",
                    "default_value": row.default_value,
                    "comment": row.comment
                })
            
            return fields
            
    except Exception as e:
        print(f"获取表字段失败: {e}")
        return []


def execute_sql(engine: Engine, sql: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """
    执行 SQL 语句
    
    Args:
        engine: 数据库引擎
        sql: SQL 语句
        params: 参数字典
        
    Returns:
        执行结果
    """
    try:
        with engine.connect() as conn:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)
            
            conn.commit()
            
            return {
                "success": True,
                "rows_affected": result.rowcount,
                "message": "执行成功"
            }
            
    except Exception as e:
        return {
            "success": False,
            "rows_affected": 0,
            "message": f"执行失败: {str(e)}"
        }