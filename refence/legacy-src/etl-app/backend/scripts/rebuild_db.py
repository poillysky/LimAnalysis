"""
重建 ETL 数据库
"""
import os
import sys
from pathlib import Path

# 添加 ETL 根目录到 Python 路径
current_dir = Path(__file__).parent
etl_backend = current_dir.parent
etl_root = etl_backend.parent

if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

# 获取配置数据库路径
cfg_db_path = os.getenv("CFG_DB_PATH", "ETL/backend/data/etl_config.sqlite")
if not os.path.isabs(cfg_db_path):
    project_root = etl_root.parent
    cfg_db_path = str(project_root / cfg_db_path)

print(f"📁 配置数据库: {cfg_db_path}")

# 删除旧数据库
if os.path.exists(cfg_db_path):
    print("🗑️  删除旧数据库...")
    os.remove(cfg_db_path)
    print("   ✅ 已删除")
else:
    print("   ℹ️  数据库不存在，将创建新数据库")

# 确保目录存在
os.makedirs(os.path.dirname(cfg_db_path), exist_ok=True)

# 创建新数据库
print("\n🔨 创建新数据库...")
from sqlalchemy import create_engine
from backend.models.base import Base

engine = create_engine(f"sqlite:///{cfg_db_path}")
Base.metadata.create_all(engine)
print("   ✅ 数据库表创建成功")

# 插入默认系统设置
print("\n⚙️  插入默认系统设置...")
from backend.utils.system_config import set_system_setting

default_settings = [
    ("backend_host", "0.0.0.0", "后端监听地址", "后端服务监听的 IP 地址", "server"),
    ("backend_port", "8001", "后端端口", "后端服务监听的端口号", "server"),
    ("frontend_url", "http://localhost:5174", "前端地址", "前端服务的访问地址（用于 CORS 配置）", "server"),
    ("log_level", "info", "日志级别", "日志输出级别（debug/info/warning/error）", "system"),
]

for key, value, name, description, category in default_settings:
    try:
        set_system_setting(key, value, name, description, category)
        print(f"   ✅ {name}: {value}")
    except Exception as e:
        print(f"   ❌ {name}: {e}")

print("\n✅ 数据库重建完成")
