"""
数据库迁移：添加系统设置表
"""
import sys
import os
from pathlib import Path
from sqlalchemy import create_engine, text

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

# 确保目录存在
os.makedirs(os.path.dirname(cfg_db_path), exist_ok=True)

# 创建引擎
engine = create_engine(f"sqlite:///{cfg_db_path}")

print("\n🚀 开始数据库迁移...")

with engine.connect() as conn:
    # 1. 创建系统设置表
    print("\n1️⃣  创建 system_settings 表...")
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param_key VARCHAR(100) UNIQUE NOT NULL,
                param_value TEXT NOT NULL,
                param_name VARCHAR(100) NOT NULL,
                description VARCHAR(255),
                category VARCHAR(50) DEFAULT 'system',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
        print("   ✅ system_settings 表创建成功")
    except Exception as e:
        print(f"   ⚠️  system_settings 表已存在或创建失败: {e}")
    
    # 2. 插入默认系统设置
    print("\n2️⃣  插入默认系统设置...")
    default_settings = [
        ("backend_host", "0.0.0.0", "后端监听地址", "后端服务监听的 IP 地址", "server"),
        ("backend_port", "8001", "后端端口", "后端服务监听的端口号", "server"),
        ("frontend_url", "http://localhost:5174", "前端地址", "前端服务的访问地址（用于 CORS 配置）", "server"),
        ("log_level", "info", "日志级别", "日志输出级别（debug/info/warning/error）", "system"),
    ]
    
    for key, value, name, description, category in default_settings:
        try:
            # 检查是否已存在
            result = conn.execute(
                text("SELECT id FROM system_settings WHERE param_key = :key"),
                {"key": key}
            )
            if result.fetchone():
                print(f"   ⏭️  {name} 已存在，跳过")
                continue
            
            # 插入
            conn.execute(
                text("""
                    INSERT INTO system_settings 
                    (param_key, param_value, param_name, description, category)
                    VALUES (:key, :value, :name, :description, :category)
                """),
                {
                    "key": key,
                    "value": value,
                    "name": name,
                    "description": description,
                    "category": category
                }
            )
            conn.commit()
            print(f"   ✅ {name}: {value}")
        except Exception as e:
            print(f"   ❌ {name}: {e}")

print("\n✅ 数据库迁移完成")
