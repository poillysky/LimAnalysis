"""
初始化 ETL 数据库表
"""
import sys
from pathlib import Path

# 添加 ETL 根目录到 Python 路径
current_dir = Path(__file__).parent
etl_root = current_dir.parent

if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

from backend.config import init_etl_config


def main():
    """初始化数据库"""
    print("=" * 50)
    print("初始化 ETL 数据库表")
    print("=" * 50)
    
    try:
        # 初始化配置
        config_manager = init_etl_config()
        
        print(f"✅ 数据库表创建成功")
        print(f"   配置数据库: {config_manager.settings.cfg_db_path}")
        
        # 检查表是否创建
        from sqlalchemy import inspect
        inspector = inspect(config_manager.engine)
        tables = inspector.get_table_names()
        
        print(f"\n已创建的 ETL 表:")
        etl_tables = [t for t in tables if t.startswith('etl_')]
        for table in etl_tables:
            print(f"  - {table}")
        
        if not etl_tables:
            print("  ⚠️  未找到 ETL 表，请检查模型定义")
        
        # 显示 ETL 配置
        etl_config = config_manager.get_etl_config()
        if etl_config:
            print(f"\nETL 配置:")
            print(f"  - 源数据库: {etl_config['source_database']}")
            print(f"  - 目标数据库: {etl_config['target_database']}")
            print(f"  - 分析数据库: {etl_config['analytics_database']}")
            print(f"  - 运行间隔: {etl_config['run_interval']} 分钟")
            print(f"  - 状态: {'启用' if etl_config['is_active'] else '禁用'}")
        else:
            print("\n⚠️  未找到 ETL 配置")
        
        print("\n✅ 初始化完成")
        
    except Exception as e:
        print(f"\n❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
