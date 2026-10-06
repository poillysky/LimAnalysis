"""
数据库迁移：添加增量更新字段配置
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.config import get_config_manager


def migrate():
    """执行迁移"""
    print("=" * 60)
    print("数据库迁移：添加增量更新字段配置")
    print("=" * 60)
    
    config_manager = get_config_manager()
    
    with config_manager.get_session() as session:
        from sqlalchemy import text
        
        try:
            # 检查字段是否已存在
            result = session.execute(text("""
                SELECT COUNT(*) as count
                FROM pragma_table_info('etl_models')
                WHERE name = 'incremental_field'
            """))
            
            count = result.scalar()
            
            if count > 0:
                print("✅ incremental_field 字段已存在，无需迁移")
                return
            
            # 添加 incremental_field 字段
            print("\n添加 incremental_field 字段...")
            session.execute(text("""
                ALTER TABLE etl_models 
                ADD COLUMN incremental_field VARCHAR(100)
            """))
            
            session.commit()
            print("✅ incremental_field 字段添加成功")
            
            # 验证
            result = session.execute(text("""
                SELECT COUNT(*) as count
                FROM pragma_table_info('etl_models')
                WHERE name = 'incremental_field'
            """))
            
            if result.scalar() > 0:
                print("✅ 迁移验证成功")
            else:
                print("❌ 迁移验证失败")
            
        except Exception as e:
            session.rollback()
            print(f"❌ 迁移失败: {e}")
            raise


if __name__ == "__main__":
    migrate()
