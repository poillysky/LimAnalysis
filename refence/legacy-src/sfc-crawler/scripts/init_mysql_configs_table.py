"""
初始化 mysql_configs 表

运行方式：
    cd backend
    python scripts/init_mysql_configs_table.py
"""
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.core.deps import get_cfg_engine


def init_mysql_configs_table():
    """初始化 mysql_configs 表"""
    engine = get_cfg_engine()
    
    with engine.connect() as conn:
        # 检查表是否存在
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='mysql_configs'
        """))
        
        if result.fetchone():
            print("✅ mysql_configs 表已存在")
            return
        
        # 创建表
        conn.execute(text("""
            CREATE TABLE mysql_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                host VARCHAR(255) NOT NULL,
                port INTEGER DEFAULT 3306,
                username VARCHAR(100) NOT NULL,
                password VARCHAR(500) NOT NULL,
                database VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.commit()
        print("✅ mysql_configs 表创建成功")


if __name__ == "__main__":
    try:
        init_mysql_configs_table()
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)
