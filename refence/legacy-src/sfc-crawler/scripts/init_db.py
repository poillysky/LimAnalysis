"""
容器启动时初始化数据库

功能：
1. 检查数据库文件是否存在
2. 如果不存在，创建数据库和表
3. 插入默认配置（可选）
"""
import os
import sqlite3
from pathlib import Path

def init_database():
    """初始化数据库"""
    # 数据库路径
    db_path = os.getenv("CFG_DB_PATH", "data/sfc_crawler_config.sqlite")
    
    # 确保目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    # 检查数据库是否已存在
    if os.path.exists(db_path):
        print(f"✅ 数据库已存在: {db_path}")
        return
    
    print(f"📦 创建数据库: {db_path}")
    
    # 连接数据库（自动创建）
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建表
    print("📋 创建表...")
    
    # 1. 爬虫配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sfc_crawler_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            description VARCHAR(255),
            sso_login_url VARCHAR(500) NOT NULL,
            sfc_base_url VARCHAR(255) NOT NULL,
            sfc_logon_path VARCHAR(255) NOT NULL DEFAULT '/SFCS/LogOn.aspx',
            sfc_data_path VARCHAR(255) NOT NULL,
            line_option VARCHAR(50) DEFAULT 'all',
            section_option VARCHAR(50) DEFAULT 'LIM',
            crawl_interval INTEGER DEFAULT 10,
            is_active BOOLEAN DEFAULT 1,
            is_running BOOLEAN DEFAULT 0,
            last_run_time DATETIME,
            last_run_status VARCHAR(20),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. 账号池表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sfc_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            username VARCHAR(100) NOT NULL,
            password TEXT NOT NULL,
            description VARCHAR(200),
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            total_use_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            last_use_time DATETIME,
            last_use_status VARCHAR(20),
            last_error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 3. 项目配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sfc_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            prefix VARCHAR(100) NOT NULL,
            sfc_code VARCHAR(100) NOT NULL,
            btype VARCHAR(20) NOT NULL,
            crawl_interval INTEGER DEFAULT 10,
            is_enabled BOOLEAN DEFAULT 1,
            last_crawl_time DATETIME,
            last_crawl_status VARCHAR(20),
            total_crawl_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 4. MySQL 配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mysql_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            host VARCHAR(255) NOT NULL,
            port INTEGER DEFAULT 3306,
            username VARCHAR(100) NOT NULL,
            password VARCHAR(500) NOT NULL,
            database VARCHAR(100) NOT NULL,
            max_connections INTEGER DEFAULT 10,
            min_connections INTEGER DEFAULT 1,
            connection_timeout INTEGER DEFAULT 30,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 5. 用户表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    
    print("✅ 数据库初始化完成")

if __name__ == "__main__":
    init_database()