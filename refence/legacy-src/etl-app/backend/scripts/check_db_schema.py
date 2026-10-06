"""
检查数据库表结构
"""
import os
import sys
import sqlite3
from pathlib import Path

# 添加项目路径
current_dir = Path(__file__).parent
etl_backend = current_dir.parent
etl_root = etl_backend.parent

sys.path.insert(0, str(etl_root))

# 获取配置数据库路径
cfg_db_path = os.getenv("CFG_DB_PATH", "ETL/backend/data/etl_config.sqlite")
if not os.path.isabs(cfg_db_path):
    project_root = etl_root.parent
    cfg_db_path = str(project_root / cfg_db_path)

print(f"📁 配置数据库: {cfg_db_path}")
print()

# 连接数据库
conn = sqlite3.connect(cfg_db_path)
cursor = conn.cursor()

# 查看所有表
print("📋 数据库中的表:")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
for table in tables:
    print(f"   - {table[0]}")
print()

# 查看 etl_configs 表结构
print("🔍 etl_configs 表结构:")
cursor.execute("PRAGMA table_info(etl_configs)")
columns = cursor.fetchall()
for col in columns:
    print(f"   {col[1]} ({col[2]})")

conn.close()
