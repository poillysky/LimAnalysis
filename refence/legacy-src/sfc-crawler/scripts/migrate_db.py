"""
数据库迁移脚本

功能：
1. 为现有数据库添加缺失的字段
2. 确保数据库结构与模型定义一致
"""
import os
import sqlite3
from pathlib import Path


def migrate_database():
    """迁移数据库结构"""
    # 数据库路径
    db_path = os.getenv("CFG_DB_PATH", "data/sfc_crawler_config.sqlite")
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    print(f"🔄 开始迁移数据库: {db_path}")
    
    # 连接数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. 检查并添加 sfc_crawler_configs.is_running 字段
        cursor.execute("PRAGMA table_info(sfc_crawler_configs)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'is_running' not in columns:
            print("📝 添加 sfc_crawler_configs.is_running 字段")
            cursor.execute("ALTER TABLE sfc_crawler_configs ADD COLUMN is_running BOOLEAN DEFAULT 0")
        else:
            print("✅ sfc_crawler_configs.is_running 字段已存在")
        
        # 2. 检查并添加 mysql_configs 表的缺失字段
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mysql_configs'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(mysql_configs)")
            mysql_columns = [column[1] for column in cursor.fetchall()]
            
            # 添加缺失的字段
            missing_fields = [
                ('max_connections', 'INTEGER DEFAULT 10'),
                ('min_connections', 'INTEGER DEFAULT 1'),
                ('connection_timeout', 'INTEGER DEFAULT 30'),
                ('is_active', 'BOOLEAN DEFAULT 1')
            ]
            
            for field_name, field_def in missing_fields:
                if field_name not in mysql_columns:
                    print(f"📝 添加 mysql_configs.{field_name} 字段")
                    cursor.execute(f"ALTER TABLE mysql_configs ADD COLUMN {field_name} {field_def}")
                else:
                    print(f"✅ mysql_configs.{field_name} 字段已存在")
        else:
            print("⚠️ mysql_configs 表不存在，跳过迁移")
        
        # 3. 检查并创建 users 表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cursor.fetchone():
            print("📝 创建 users 表")
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            print("✅ users 表已存在")
        
        conn.commit()
        print("✅ 数据库迁移完成")
        
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_database()