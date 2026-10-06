"""
删除 etl_models 表中的 backfill_hours 字段

原因：backfill_hours 应该只在全局配置（etl_config）中配置，
避免在模型级别重复配置导致混用。
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from backend.config import get_config_manager


def migrate():
    """执行迁移"""
    config_manager = get_config_manager()
    
    with config_manager.get_session() as session:
        try:
            # 检查字段是否存在
            check_sql = """
                SELECT COUNT(*) as count
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                AND table_name = 'etl_models'
                AND column_name = 'backfill_hours'
            """
            result = session.execute(text(check_sql)).fetchone()
            
            if result and result[0] > 0:
                print("🔧 删除 etl_models.backfill_hours 字段...")
                
                # 删除字段
                alter_sql = """
                    ALTER TABLE etl_models
                    DROP COLUMN backfill_hours
                """
                session.execute(text(alter_sql))
                session.commit()
                
                print("✅ 字段删除成功")
            else:
                print("ℹ️  字段不存在，无需删除")
                
        except Exception as e:
            session.rollback()
            print(f"❌ 迁移失败: {e}")
            raise


if __name__ == "__main__":
    print("=" * 80)
    print("开始迁移：删除 etl_models.backfill_hours 字段")
    print("=" * 80)
    migrate()
    print("=" * 80)
    print("迁移完成")
    print("=" * 80)
