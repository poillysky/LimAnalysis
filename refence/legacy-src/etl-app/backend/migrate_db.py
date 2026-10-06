"""
迁移 ETL 数据库表结构

本脚本使用 ETL 自己的 SQLite 数据库（ETL/backend/data/etl_config.sqlite）
不依赖 DataLim4 的配置系统
"""
import sys
from pathlib import Path

# 添加路径
current_dir = Path(__file__).parent
etl_root = current_dir.parent

if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

from backend.config import get_config_manager
from sqlalchemy import text


def main():
    """迁移数据库"""
    print("=" * 50)
    print("迁移 ETL 数据库表结构")
    print("=" * 50)
    
    try:
        config_manager = get_config_manager()
        engine = config_manager.engine
        
        with engine.connect() as conn:
            # 删除旧的 ETL 表
            print("\n删除旧表...")
            tables_to_drop = [
                'etl_source_fields',
                'etl_model_fields',
                'etl_models',
                'etl_configs'
            ]
            
            for table in tables_to_drop:
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                    print(f"  ✅ 删除表: {table}")
                except Exception as e:
                    print(f"  ⚠️  删除表 {table} 失败: {e}")
            
            conn.commit()
        
        print("\n重新创建表...")
        from backend.config import init_etl_config
        config_manager = init_etl_config()
        
        print("✅ 表结构迁移完成")
        
        # 检查表
        from sqlalchemy import inspect
        inspector = inspect(config_manager.engine)
        tables = inspector.get_table_names()
        
        print(f"\n当前 ETL 表:")
        etl_tables = [t for t in tables if t.startswith('etl_') or t.startswith('mysql_') or t.startswith('system_')]
        for table in etl_tables:
            columns = inspector.get_columns(table)
            print(f"  - {table} ({len(columns)} 列)")
        
        # 显示配置
        etl_config = config_manager.get_etl_config()
        if etl_config:
            print(f"\nETL 配置:")
            print(f"  - 源数据库: {etl_config['source_database']}")
            print(f"  - 目标数据库: {etl_config['target_database']}")
            print(f"  - 分析数据库: {etl_config['analytics_database']}")
        
        print(f"\n数据库位置: {config_manager.cfg_db_path}")
        print("\n✅ 迁移完成")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
