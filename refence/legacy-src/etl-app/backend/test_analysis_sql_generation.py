"""
测试分析表 SQL 生成功能
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.core.sql_generator import SqlGenerator


def test_analysis_sql_generation():
    """测试分析表 SQL 生成"""
    
    print("\n" + "=" * 80)
    print("测试分析表 SQL 生成")
    print("=" * 80)
    
    # 创建 SQL 生成器
    sql_generator = SqlGenerator()
    
    # 测试数据：模拟用户配置
    fields = [
        # 维度字段
        {
            'target_field': 'machine',
            'source_field': '机台',
            'field_type': '文本',
            'field_category': 'dimension',
            'derive_level': 1
        },
        {
            'target_field': 'product_type',
            'source_field': '产品型号',
            'field_type': '文本',
            'field_category': 'dimension',
            'derive_level': 1
        },
        # 度量字段
        {
            'target_field': 'total_qty',
            'source_field': '数量',
            'field_type': '整数',
            'field_category': 'measure',
            'aggregate_func': 'SUM',
            'derive_level': 1
        },
        {
            'target_field': 'pass_qty',
            'source_field': '合格数',
            'field_type': '整数',
            'field_category': 'measure',
            'aggregate_func': 'SUM',
            'derive_level': 1
        },
        {
            'target_field': 'avg_temp',
            'source_field': '温度',
            'field_type': '小数',
            'field_category': 'measure',
            'aggregate_func': 'AVG',
            'derive_level': 1
        },
        {
            'target_field': 'record_count',
            'source_field': '*',
            'field_type': '整数',
            'field_category': 'measure',
            'aggregate_func': 'COUNT',
            'derive_level': 1
        },
        # 派生字段
        {
            'target_field': 'pass_rate',
            'formula': '`pass_qty` / `total_qty` * 100',
            'field_type': '小数',
            'field_category': 'derived',
            'derive_level': 2
        },
        {
            'target_field': 'avg_qty_per_record',
            'formula': '`total_qty` / `record_count`',
            'field_type': '小数',
            'field_category': 'derived',
            'derive_level': 2
        }
    ]
    
    # 生成 SQL
    print("\n📝 生成分析表 SQL...")
    sql_path = sql_generator.generate_analysis_model_sql(
        model_name='eagle_hourly_stats',
        table_name='analysis_eagle_hourly',
        source_table='link_eagle_rcv',
        source_database='link_db',
        target_database='analysis_db',
        time_field='ServerTime',
        granularity='hour',
        time_field_name='hour',
        fields=fields,
        description='Eagle 设备按小时聚合的统计分析',
        project_name='SFC'
    )
    
    print(f"\n✅ SQL 文件已生成: {sql_path}")
    
    # 读取并显示生成的 SQL
    print("\n" + "=" * 80)
    print("生成的 SQL 内容:")
    print("=" * 80)
    
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
        print(sql_content)
    
    print("\n" + "=" * 80)
    print("✅ 测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    test_analysis_sql_generation()
