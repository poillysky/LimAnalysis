"""
添加分析表相关字段的数据库迁移脚本（SQLite）
执行方式: python backend/migrations/migrate_analysis_fields.py
"""
import sqlite3
import os
from pathlib import Path


def migrate_database():
    """执行数据库迁移"""
    
    # 获取数据库文件路径
    project_root = Path(__file__).parent.parent.parent
    db_path = project_root / "backend" / "data" / "etl_config.sqlite"
    
    if not db_path.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    print(f"📂 数据库路径: {db_path}")
    
    try:
        # 连接数据库
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        print("\n" + "=" * 80)
        print("开始执行数据库迁移...")
        print("=" * 80)
        
        # ========== 1. 检查并添加 etl_models 表的字段 ==========
        print("\n📋 步骤 1: 检查 etl_models 表...")
        
        # 获取现有列
        cursor.execute("PRAGMA table_info(etl_models)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        print(f"   现有列: {', '.join(sorted(existing_columns))}")
        
        # 需要添加的列
        new_columns = {
            'time_field': "ALTER TABLE etl_models ADD COLUMN time_field VARCHAR(100)",
            'granularity': "ALTER TABLE etl_models ADD COLUMN granularity VARCHAR(20) DEFAULT 'hour'",
            'time_field_name': "ALTER TABLE etl_models ADD COLUMN time_field_name VARCHAR(100) DEFAULT 'hour'"
        }
        
        added_count = 0
        for col_name, sql in new_columns.items():
            if col_name not in existing_columns:
                print(f"   ➕ 添加列: {col_name}")
                cursor.execute(sql)
                added_count += 1
            else:
                print(f"   ✓ 列已存在: {col_name}")
        
        if added_count > 0:
            print(f"   ✅ 成功添加 {added_count} 个列到 etl_models 表")
        else:
            print(f"   ✅ etl_models 表已是最新状态")
        
        # ========== 2. 检查并添加 etl_model_fields 表的字段 ==========
        print("\n📋 步骤 2: 检查 etl_model_fields 表...")
        
        # 获取现有列
        cursor.execute("PRAGMA table_info(etl_model_fields)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        print(f"   现有列: {', '.join(sorted(existing_columns))}")
        
        # 需要添加的列
        new_columns = {
            'field_category': "ALTER TABLE etl_model_fields ADD COLUMN field_category VARCHAR(20)",
            'aggregate_func': "ALTER TABLE etl_model_fields ADD COLUMN aggregate_func VARCHAR(50)"
        }
        
        added_count = 0
        for col_name, sql in new_columns.items():
            if col_name not in existing_columns:
                print(f"   ➕ 添加列: {col_name}")
                cursor.execute(sql)
                added_count += 1
            else:
                print(f"   ✓ 列已存在: {col_name}")
        
        if added_count > 0:
            print(f"   ✅ 成功添加 {added_count} 个列到 etl_model_fields 表")
        else:
            print(f"   ✅ etl_model_fields 表已是最新状态")
        
        # ========== 3. 更新现有数据的默认值 ==========
        print("\n📋 步骤 3: 更新现有数据的默认值...")
        
        cursor.execute("""
            UPDATE etl_models 
            SET granularity = 'hour', time_field_name = 'hour' 
            WHERE model_type = 'analysis' 
            AND (granularity IS NULL OR time_field_name IS NULL)
        """)
        updated_count = cursor.rowcount
        
        if updated_count > 0:
            print(f"   ✅ 更新了 {updated_count} 条分析表记录的默认值")
        else:
            print(f"   ✅ 无需更新默认值")
        
        # ========== 4. 提交更改 ==========
        conn.commit()
        
        # ========== 5. 验证迁移结果 ==========
        print("\n📋 步骤 4: 验证迁移结果...")
        
        # 验证 etl_models 表
        cursor.execute("PRAGMA table_info(etl_models)")
        columns = cursor.fetchall()
        target_columns = {'time_field', 'granularity', 'time_field_name'}
        found_columns = {col[1] for col in columns if col[1] in target_columns}
        
        print(f"\n   etl_models 表新增字段:")
        for col in columns:
            if col[1] in target_columns:
                print(f"      ✓ {col[1]} ({col[2]})")
        
        # 验证 etl_model_fields 表
        cursor.execute("PRAGMA table_info(etl_model_fields)")
        columns = cursor.fetchall()
        target_columns = {'field_category', 'aggregate_func'}
        found_columns = {col[1] for col in columns if col[1] in target_columns}
        
        print(f"\n   etl_model_fields 表新增字段:")
        for col in columns:
            if col[1] in target_columns:
                print(f"      ✓ {col[1]} ({col[2]})")
        
        # 关闭连接
        conn.close()
        
        print("\n" + "=" * 80)
        print("✅ 数据库迁移完成！")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = migrate_database()
    exit(0 if success else 1)
