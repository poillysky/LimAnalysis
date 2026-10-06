"""
初始化 ETL 数据库表
"""
import sys
from pathlib import Path

# 添加 ETL 根目录到 Python 路径
current_dir = Path(__file__).parent
etl_backend = current_dir.parent
etl_root = etl_backend.parent

if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

from backend.config import init_etl_config
from backend.utils.system_config import set_system_setting

if __name__ == "__main__":
    print("🚀 开始初始化 ETL 数据库...")
    
    try:
        config_manager = init_etl_config()
        print("✅ ETL 数据库初始化成功")
        print(f"   配置数据库: {config_manager.settings.cfg_db_path}")
        print("\n已创建的表:")
        print("  - etl_configs (ETL 配置表)")
        print("  - mysql_configs (MySQL 配置表)")
        print("  - system_settings (系统设置表)")
        
        # 初始化默认系统设置
        print("\n🔧 初始化默认系统设置...")
        
        default_settings = [
            ("backend_host", "0.0.0.0", "后端监听地址", "后端服务监听的 IP 地址", "server"),
            ("backend_port", "8001", "后端端口", "后端服务监听的端口号", "server"),
            ("frontend_url", "http://localhost:5174", "前端地址", "前端服务的访问地址（用于 CORS 配置）", "server"),
            ("log_level", "info", "日志级别", "日志输出级别（debug/info/warning/error）", "system"),
        ]
        
        for key, value, name, description, category in default_settings:
            try:
                set_system_setting(key, value, name, description, category)
                print(f"  ✅ {name}: {value}")
            except Exception as e:
                print(f"  ⚠️  {name}: {e}")
        
        print("\n✅ 初始化完成")
        
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

