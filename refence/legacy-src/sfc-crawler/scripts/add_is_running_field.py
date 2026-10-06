"""
添加 is_running 字段到 sfc_crawler_configs 表

用途：防止爬虫任务并发执行
"""
import sqlite3
import os
from pathlib import Path

def add_is_running_field():
    """添加 is_running 字段"""
    # 获取数据库路径
    cfg_db_path = os.getenv("CFG_DB_PATH", "backend/data/sfc_crawler_config.sqlite")
    
    if not os.path.isabs(cfg_db_path):
        # 使用正斜杠
        project_root = Path(__file__).parent.parent.parent
        cfg_db_path = project_root / cfg_db_path
        cfg_db_path = str(cfg_db_path).replace('\\', '/')
    
    print(f"数据库路径: {cfg_db_path}")
    
    # 连接数据库
    conn = sqlite3.connect(cfg_db_path)
    cursor = conn.cursor()
    
    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(sfc_crawler_configs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'is_running' in columns:
            print("✅ is_running 字段已存在，无需添加")
            return
        
        # 添加字段
        print("添加 is_running 字段...")
        cursor.execute("""
            ALTER TABLE sfc_crawler_configs 
            ADD COLUMN is_running BOOLEAN DEFAULT 0
        """)
        
        conn.commit()
        print("✅ is_running 字段添加成功")
        
        # 验证
        cursor.execute("PRAGMA table_info(sfc_crawler_configs)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"\n当前字段列表: {columns}")
        
        # 查询当前配置
        cursor.execute("SELECT id, name, is_active, is_running FROM sfc_crawler_configs")
        configs = cursor.fetchall()
        print(f"\n当前配置:")
        for config in configs:
            print(f"  ID: {config[0]}, 名称: {config[1]}, 启用: {config[2]}, 运行中: {config[3]}")
        
    except Exception as e:
        print(f"❌ 添加字段失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    add_is_running_field()
