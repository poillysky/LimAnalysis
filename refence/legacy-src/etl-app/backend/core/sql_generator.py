"""
SQL 生成器 - 根据模型配置生成标准 SQL 文件
"""
import os
from pathlib import Path
from typing import List, Dict, Optional


class SqlGenerator:
    """SQL 生成器"""
    
    def __init__(self, sql_models_dir: str = "sql_models"):
        """
        初始化 SQL 生成器
        
        Args:
            sql_models_dir: SQL 模型文件目录
        """
        # 确保路径是相对于 ETL 根目录的绝对路径
        if not os.path.isabs(sql_models_dir):
            etl_root = Path(__file__).parent.parent.parent
            self.sql_models_dir = str(etl_root / sql_models_dir)
        else:
            self.sql_models_dir = sql_models_dir
    
    def generate_link_model_sql(
        self,
        model_name: str,
        table_name: str,
        source_table: str,
        source_database: str,
        target_database: str,
        fields: List[Dict],
        unique_key_type: str = "none",
        unique_key: Optional[str] = None,
        unique_keys: Optional[List[str]] = None,
        description: str = "",
        project_name: str = "default",
        view_time_field: Optional[str] = None
    ) -> str:
        """
        生成关联表模型 SQL 文件
        
        字段配置格式：
        - direct: 使用 source_field（源字段名）
        - derived: 使用 formula（SQL 表达式）
        - constant: 使用 constant_value（固定值）
        
        Args:
            model_name: 模型名称
            table_name: 目标表名
            source_table: 源表名
            source_database: 源数据库
            target_database: 目标数据库
            fields: 字段配置列表
            unique_key_type: 唯一键类型
            unique_key: 单字段唯一键
            unique_keys: 复合唯一键列表
            description: 模型描述
            project_name: 项目名称
            
        Returns:
            生成的 SQL 文件路径
        """
        # 构建 SQL 注释头部
        header_lines = [
            f"-- 关联表模型: {model_name}",
            f"-- 描述: {description or '无'}",
            f"-- 源表: {source_database}.{source_table}",
            f"-- 目标表: {target_database}.{table_name}",
            f"-- 项目: {project_name}",
            "--",
            f"-- 唯一键类型: {unique_key_type}",
        ]
        
        if unique_key_type == 'single' and unique_key:
            header_lines.append(f"-- 唯一键: {unique_key}")
        elif unique_key_type == 'composite' and unique_keys:
            header_lines.append(f"-- 唯一键: {', '.join(unique_keys)}")
        
        header_lines.extend([
            "--",
            "-- 增量更新策略:",
            "-- - 全量刷新: DELETE FROM 目标表 + INSERT 全部数据",
            "-- - 增量更新: INSERT 新数据 (WHERE upload_time > 最后更新时间)",
            "--",
            ""
        ])
        
        # 按映射类型和派生层级分组处理字段
        direct_fields = []
        level1_derived_fields = []
        level2_derived_fields = []
        constant_fields = []
        
        for field in fields:
            # 兼容 camelCase 和 snake_case
            mapping_type = field.get('mapping_type') or field.get('mappingType', 'direct')
            target_field = field.get('target_field') or field.get('targetField', '')
            derive_level = field.get('derive_level') or field.get('deriveLevel', 1)
            
            if mapping_type == 'direct':
                # 直接映射：使用 source_field（新格式）
                source_field_name = field.get('source_field') or field.get('sourceField', '')
                
                # 如果 source_field 为空，使用 target_field（同名字段）
                if not source_field_name or not source_field_name.strip():
                    source_field_name = target_field
                
                source_field = source_field_name.strip().strip('`')
                
                if source_field == target_field:
                    direct_fields.append(f"    `{source_field}`")
                else:
                    direct_fields.append(f"    `{source_field}` AS `{target_field}`")
            
            elif mapping_type == 'derived':
                # 派生字段：使用 formula（SQL 表达式）
                formula = field.get('formula', '')
                if formula and formula.strip():
                    # 处理公式中的字段引用
                    processed_formula = self._process_formula(formula)
                    field_sql = f"    {processed_formula} AS `{target_field}`"
                    
                    # 根据派生层级分组
                    if derive_level == 2:
                        level2_derived_fields.append(field_sql)
                    else:
                        level1_derived_fields.append(field_sql)
            
            elif mapping_type == 'constant':
                # 固定值：使用 constant_value
                constant_value = field.get('constant_value') or field.get('constantValue', '')
                if constant_value:
                    constant_fields.append(f"    '{constant_value}' AS `{target_field}`")
        
        # 判断是否需要使用 CTE（如果有 Level 2 字段）
        use_cte = len(level2_derived_fields) > 0
        
        if use_cte:
            # 使用 CTE 方式生成 SQL
            sql_content = self._generate_sql_with_cte(
                header_lines=header_lines,
                source_database=source_database,
                source_table=source_table,
                direct_fields=direct_fields,
                level1_derived_fields=level1_derived_fields,
                level2_derived_fields=level2_derived_fields,
                constant_fields=constant_fields
            )
        else:
            # 使用简单 SELECT 方式生成 SQL
            sql_content = self._generate_simple_sql(
                header_lines=header_lines,
                source_database=source_database,
                source_table=source_table,
                direct_fields=direct_fields,
                level1_derived_fields=level1_derived_fields,
                constant_fields=constant_fields
            )
        
        # 确定文件路径并创建目录
        layer_dir = Path(self.sql_models_dir) / "layer1"
        layer_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入关联表 SQL 文件
        file_path = layer_dir / f"{table_name}.sql"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(sql_content)
        
        print(f"✅ 关联表 SQL 已生成: {file_path}")
        
        # 生成视图 SQL（显示最近3小时的最新数据）
        # 使用配置的时间字段，如果未配置则使用 etl_timestamp
        time_field_for_view = view_time_field if view_time_field and view_time_field.strip() else "etl_timestamp"
        view_sql_path = self._generate_recent_view_sql(
            model_name=model_name,
            table_name=table_name,
            target_database=target_database,
            unique_key_type=unique_key_type,
            unique_key=unique_key,
            unique_keys=unique_keys,
            project_name=project_name,
            time_field=time_field_for_view
        )
        
        return str(file_path)
    
    def _generate_simple_sql(
        self,
        header_lines: List[str],
        source_database: str,
        source_table: str,
        direct_fields: List[str],
        level1_derived_fields: List[str],
        constant_fields: List[str]
    ) -> str:
        """
        生成简单的 SELECT SQL（只有 Level 1 字段时）
        
        Args:
            header_lines: SQL 注释头部
            source_database: 源数据库
            source_table: 源表名
            direct_fields: 直接映射字段列表
            level1_derived_fields: Level 1 派生字段列表
            constant_fields: 固定值字段列表
            
        Returns:
            生成的 SQL 内容
        """
        # 合并所有字段
        all_fields = []
        
        # 添加直接映射字段
        if direct_fields:
            all_fields.extend(direct_fields)
        
        # 添加 Level 1 派生字段
        if level1_derived_fields:
            all_fields.extend(level1_derived_fields)
        
        # 添加固定值字段
        if constant_fields:
            all_fields.extend(constant_fields)
        
        # 添加元数据字段
        all_fields.append("    CURRENT_TIMESTAMP() AS `etl_timestamp`")
        
        # 添加逗号（最后一个字段不加）
        for i in range(len(all_fields) - 1):
            all_fields[i] += ","
        
        # 构建完整的 SQL
        sql_content = f"""{chr(10).join(header_lines)}
SELECT
{chr(10).join(all_fields)}
FROM {source_database}.{source_table}
"""
        
        return sql_content
    
    def _generate_sql_with_cte(
        self,
        header_lines: List[str],
        source_database: str,
        source_table: str,
        direct_fields: List[str],
        level1_derived_fields: List[str],
        level2_derived_fields: List[str],
        constant_fields: List[str]
    ) -> str:
        """
        生成带 CTE 的 SQL（有 Level 2 字段时）
        
        CTE 结构：
        WITH level1 AS (
            SELECT
                *,  -- 源表所有字段
                -- Level 1 派生字段
                SUBSTRING(`SN`, 1, 3) AS `product_type`
            FROM source_database.source_table
        )
        SELECT
            -- 直接映射字段（可能有别名）
            `SN`,
            `upload_time` AS `上传时间`,
            -- Level 1 字段
            `product_type`,
            -- Level 2 派生字段（可引用源表字段和 Level 1 字段）
            CONCAT(`product_type`, '-', `upload_time`) AS `product_info`,
            -- 固定值字段
            'SFC_RAW' AS `data_source`,
            -- 元数据
            CURRENT_TIMESTAMP() AS `etl_timestamp`
        FROM level1
        
        Args:
            header_lines: SQL 注释头部
            source_database: 源数据库
            source_table: 源表名
            direct_fields: 直接映射字段列表
            level1_derived_fields: Level 1 派生字段列表
            level2_derived_fields: Level 2 派生字段列表
            constant_fields: 固定值字段列表
            
        Returns:
            生成的 SQL 内容
        """
        # ========== 构建 CTE 部分（Level 1） ==========
        cte_fields = []
        
        # 添加直接映射字段（需要在 level1 中定义别名）
        if direct_fields:
            cte_fields.extend(direct_fields)
        
        # 添加 Level 1 派生字段
        if level1_derived_fields:
            cte_fields.extend(level1_derived_fields)
        
        # 添加逗号（最后一个字段不加）
        for i in range(len(cte_fields) - 1):
            cte_fields[i] += ","
        
        # ========== 构建主查询部分（Level 2） ==========
        main_fields = []
        
        # 从直接映射字段中提取目标字段名（用于主查询）
        # 例如：从 "`upload_time` AS `上传时间`" 提取 "`上传时间`"
        if direct_fields:
            for field_sql in direct_fields:
                # 查找 AS 关键字
                if ' AS ' in field_sql:
                    # 提取 AS 后面的字段名
                    field_name = field_sql.split(' AS ')[-1].strip()
                    main_fields.append(f"    {field_name}")
                else:
                    # 没有 AS，直接使用字段名
                    main_fields.append(field_sql)
        
        # 从 Level 1 派生字段中提取字段名（用于主查询）
        # 例如：从 "SUBSTRING(`SN`, 1, 3) AS `product_type`" 提取 "`product_type`"
        if level1_derived_fields:
            for field_sql in level1_derived_fields:
                # 查找 AS 关键字
                if ' AS ' in field_sql:
                    # 提取 AS 后面的字段名
                    field_name = field_sql.split(' AS ')[-1].strip()
                    main_fields.append(f"    {field_name}")
        
        # 添加 Level 2 派生字段
        if level2_derived_fields:
            main_fields.extend(level2_derived_fields)
        
        # 添加固定值字段
        if constant_fields:
            main_fields.extend(constant_fields)
        
        # 添加元数据字段
        main_fields.append("    CURRENT_TIMESTAMP() AS `etl_timestamp`")
        
        # 添加逗号（最后一个字段不加）
        for i in range(len(main_fields) - 1):
            main_fields[i] += ","
        
        # ========== 构建完整的 SQL ==========
        sql_content = f"""{chr(10).join(header_lines)}
WITH level1 AS (
    SELECT
{chr(10).join(cte_fields)}
    FROM {source_database}.{source_table}
)
SELECT
{chr(10).join(main_fields)}
FROM level1
"""
        
        return sql_content
    
    def generate_analysis_model_sql(
        self,
        model_name: str,
        table_name: str,
        source_table: str,
        source_database: str,
        target_database: str,
        time_field: str,
        granularity: str,
        time_field_name: str,
        fields: List[Dict],
        description: str = "",
        project_name: str = "default"
    ) -> str:
        """
        生成分析表模型 SQL 文件（支持多层派生）
        
        生成逻辑：
        1. 时间分组（大分组）：根据时间字段和聚合细度分组
        2. 维度透视（小分组）：在每个时间段内，按维度字段分组
        3. 度量计算：对每个分组使用聚合函数计算度量值
        4. 派生计算：基于已配置字段进行公式计算
        
        注意：回算时间使用全局配置（etl_config.backfill_hours）
        
        Args:
            model_name: 模型名称
            table_name: 目标表名
            source_table: 源表名
            source_database: 源数据库
            target_database: 目标数据库
            time_field: 时间字段名
            granularity: 聚合细度（hour/day/week/month）
            time_field_name: 生成的时间字段名
            fields: 字段配置列表
            description: 模型描述
            project_name: 项目名称
            
        Returns:
            生成的 SQL 文件路径
        """
        # 按层级和类别分组字段
        dimension_fields = []  # 维度字段（层级 1，用于透视）
        measure_fields = []    # 度量字段（层级 1，聚合计算）
        derived_fields = []    # 派生字段（层级 2，基于聚合结果）
        
        for field in fields:
            category = field.get('field_category', '')
            derive_level = field.get('derive_level', 1)
            
            if derive_level == 1:
                if category == 'dimension':
                    dimension_fields.append(field)
                elif category == 'measure':
                    measure_fields.append(field)
            elif derive_level == 2:
                if category == 'derived':
                    derived_fields.append(field)
        
        # 判断是否需要使用 CTE
        use_cte = len(derived_fields) > 0
        
        # ========== 构建层级 1（聚合层）==========
        select_parts = []
        group_by_parts = []
        
        # 步骤 1: 时间分组（大分组）
        time_expr = self._get_time_aggregation_expr(time_field, granularity)
        select_parts.append(f"    {time_expr} AS `{time_field_name}`")
        group_by_parts.append(time_expr)
        
        # 步骤 2: 维度透视（小分组）
        for dim in dimension_fields:
            source = dim.get('source_field', '')
            target = dim.get('target_field', '')
            if source and target:
                select_parts.append(f"    `{source}` AS `{target}`")
                group_by_parts.append(f"`{source}`")
        
        # 步骤 3: 度量计算（聚合函数）
        for measure in measure_fields:
            source = measure.get('source_field', '')
            target = measure.get('target_field', '')
            func = measure.get('aggregate_func', 'SUM')
            
            if func == 'COUNT' and (not source or source == '*'):
                select_parts.append(f"    COUNT(*) AS `{target}`")
            else:
                select_parts.append(f"    {func}(`{source}`) AS `{target}`")
        
        # ========== 构建完整 SQL ==========
        if not use_cte:
            # 没有派生字段，直接返回聚合查询
            sql_content = f"""-- 分析表模型: {model_name}
-- 描述: {description or '无'}
-- 源表: {source_database}.{source_table}
-- 目标表: {target_database}.{table_name}
-- 项目: {project_name}
--
-- 聚合细度: {granularity}
-- 回算时间: 使用全局配置（etl_config.backfill_hours）
--
-- 生成逻辑:
-- 1. 时间分组: 按 {granularity} 聚合
-- 2. 维度透视: 按 {len(dimension_fields)} 个维度字段分组
-- 3. 度量计算: {len(measure_fields)} 个聚合指标
--

SELECT
{chr(10).join([f"{part}," if i < len(select_parts) - 1 else part for i, part in enumerate(select_parts)])}
FROM {source_database}.{source_table}
GROUP BY {', '.join(group_by_parts)}
ORDER BY `{time_field_name}` DESC
"""
        else:
            # 有派生字段，使用 CTE
            # 步骤 4: 派生计算（基于已配置字段）
            derived_select_parts = ['    *']  # 保留所有聚合字段
            for derived in derived_fields:
                formula = derived.get('formula', '')
                target = derived.get('target_field', '')
                
                if formula and target:
                    # 处理公式中的字段引用
                    processed_formula = self._process_formula(formula)
                    derived_select_parts.append(f"    {processed_formula} AS `{target}`")
            
            sql_content = f"""-- 分析表模型: {model_name}
-- 描述: {description or '无'}
-- 源表: {source_database}.{source_table}
-- 目标表: {target_database}.{table_name}
-- 项目: {project_name}
--
-- 聚合细度: {granularity}
-- 回算时间: 使用全局配置（etl_config.backfill_hours）
--
-- 生成逻辑:
-- 1. 时间分组: 按 {granularity} 聚合
-- 2. 维度透视: 按 {len(dimension_fields)} 个维度字段分组
-- 3. 度量计算: {len(measure_fields)} 个聚合指标
-- 4. 派生计算: {len(derived_fields)} 个派生字段
--

WITH aggregated AS (
    SELECT
{chr(10).join([f"{part}," if i < len(select_parts) - 1 else part for i, part in enumerate(select_parts)])}
    FROM {source_database}.{source_table}
    GROUP BY {', '.join(group_by_parts)}
)
SELECT
{chr(10).join([f"{part}," if i < len(derived_select_parts) - 1 else part for i, part in enumerate(derived_select_parts)])}
FROM aggregated
ORDER BY `{time_field_name}` DESC
"""
        
        # 确定文件路径并创建目录
        layer_dir = Path(self.sql_models_dir) / "layer2"
        layer_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        file_path = layer_dir / f"{table_name}.sql"
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(sql_content)
        
        print(f"✅ 分析表 SQL 已生成: {file_path}")
        
        return str(file_path)
    
    def _get_time_aggregation_expr(self, time_field: str, granularity: str) -> str:
        """
        生成时间聚合表达式
        
        Args:
            time_field: 时间字段名
            granularity: 聚合细度
            
        Returns:
            时间聚合 SQL 表达式
        """
        if granularity == 'hour':
            return f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d %H:00:00')"
        elif granularity == 'day':
            return f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d')"
        elif granularity == 'week':
            return f"DATE_FORMAT(`{time_field}`, '%Y-%u')"  # 年-周数
        elif granularity == 'month':
            return f"DATE_FORMAT(`{time_field}`, '%Y-%m')"
        else:
            # 默认按小时
            return f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d %H:00:00')"
    
    def _process_formula(self, formula: str) -> str:
        """
        处理 SQL 公式，将方括号替换为反引号
        
        Args:
            formula: 原始公式
            
        Returns:
            处理后的公式
        """
        # 将方括号替换为反引号（MySQL 语法）
        formula = formula.replace('[', '`').replace(']', '`')
        formula = formula.replace('【', '`').replace('】', '`')
        
        return formula
    
    def _generate_recent_view_sql(
        self,
        model_name: str,
        table_name: str,
        target_database: str,
        unique_key_type: str,
        unique_key: Optional[str],
        unique_keys: Optional[List[str]],
        project_name: str,
        time_field: str = "etl_timestamp"
    ) -> str:
        """
        生成最近数据视图 SQL
        
        显示时间字段在最近3小时内的最新数据
        
        Args:
            model_name: 模型名称
            table_name: 目标表名
            target_database: 目标数据库
            unique_key_type: 唯一键类型
            unique_key: 单字段唯一键
            unique_keys: 复合唯一键列表
            project_name: 项目名称
            time_field: 时间字段名（默认使用 etl_timestamp）
            
        Returns:
            生成的视图 SQL 文件路径
        """
        view_name = f"v_{table_name}_recent"
        
        # 构建视图 SQL 注释头部
        header_lines = [
            f"-- 最近数据视图: {view_name}",
            f"-- 基于表: {target_database}.{table_name}",
            f"-- 描述: 显示 {time_field} 在最近3小时内的最新数据",
            f"-- 项目: {project_name}",
            "--",
            f"-- 唯一键类型: {unique_key_type}",
        ]
        
        if unique_key_type == 'single' and unique_key:
            header_lines.append(f"-- 唯一键: {unique_key}")
        elif unique_key_type == 'composite' and unique_keys:
            header_lines.append(f"-- 唯一键: {', '.join(unique_keys)}")
        
        header_lines.extend([
            "--",
            "-- 使用说明:",
            f"-- 1. 只显示 {time_field} 在最近3小时内的数据",
            "-- 2. 如果有唯一键，每个唯一键只显示最新的一条记录",
            f"-- 3. 按 {time_field} 降序排列",
            "--",
            ""
        ])
        
        # 构建视图 SQL
        if unique_key_type == 'none':
            # 没有唯一键：直接过滤最近3小时的数据
            view_sql = f"""{chr(10).join(header_lines)}
CREATE OR REPLACE VIEW {target_database}.{view_name} AS
SELECT *
FROM {target_database}.{table_name}
WHERE `{time_field}` >= DATE_SUB(NOW(), INTERVAL 3 HOUR)
ORDER BY `{time_field}` DESC;
"""
        
        elif unique_key_type == 'single' and unique_key:
            # 单字段唯一键：使用窗口函数获取每个唯一键的最新记录
            view_sql = f"""{chr(10).join(header_lines)}
CREATE OR REPLACE VIEW {target_database}.{view_name} AS
SELECT *
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY `{unique_key}` ORDER BY `{time_field}` DESC) AS rn
    FROM {target_database}.{table_name}
    WHERE `{time_field}` >= DATE_SUB(NOW(), INTERVAL 3 HOUR)
) t
WHERE rn = 1
ORDER BY `{time_field}` DESC;
"""
        
        elif unique_key_type == 'composite' and unique_keys:
            # 复合唯一键：使用窗口函数获取每个唯一键组合的最新记录
            partition_fields = ', '.join([f"`{key}`" for key in unique_keys])
            view_sql = f"""{chr(10).join(header_lines)}
CREATE OR REPLACE VIEW {target_database}.{view_name} AS
SELECT *
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY {partition_fields} ORDER BY `{time_field}` DESC) AS rn
    FROM {target_database}.{table_name}
    WHERE `{time_field}` >= DATE_SUB(NOW(), INTERVAL 3 HOUR)
) t
WHERE rn = 1
ORDER BY `{time_field}` DESC;
"""
        else:
            # 默认：没有唯一键
            view_sql = f"""{chr(10).join(header_lines)}
CREATE OR REPLACE VIEW {target_database}.{view_name} AS
SELECT *
FROM {target_database}.{table_name}
WHERE `{time_field}` >= DATE_SUB(NOW(), INTERVAL 3 HOUR)
ORDER BY `{time_field}` DESC;
"""
        
        # 确定文件路径并创建目录
        views_dir = Path(self.sql_models_dir) / "views"
        views_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入视图 SQL 文件
        view_file_path = views_dir / f"{view_name}.sql"
        with open(view_file_path, 'w', encoding='utf-8') as f:
            f.write(view_sql)
        
        print(f"✅ 视图 SQL 已生成: {view_file_path}")
        
        return str(view_file_path)
    
    def delete_model_sql(self, sql_path: str) -> bool:
        """
        删除模型 SQL 文件
        
        Args:
            sql_path: SQL 文件路径
            
        Returns:
            是否删除成功
        """
        try:
            # 如果是相对路径，转换为绝对路径
            if not os.path.isabs(sql_path):
                etl_root = Path(__file__).parent.parent.parent
                sql_path = str(etl_root / sql_path)
            
            file_path = Path(sql_path)
            if file_path.exists():
                file_path.unlink()
                print(f"✅ SQL 文件已删除: {sql_path}")
                return True
            else:
                print(f"⚠️  SQL 文件不存在: {sql_path}")
                return False
                
        except Exception as e:
            print(f"❌ 删除 SQL 文件失败: {e}")
            return False
    
    def validate_sql_file(self, sql_path: str) -> Dict[str, any]:
        """
        验证 SQL 文件
        
        Args:
            sql_path: SQL 文件路径
            
        Returns:
            验证结果
        """
        try:
            with open(sql_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            from backend.utils.validators import validate_sql_file
            return validate_sql_file(sql_content)
            
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"读取文件失败: {str(e)}"],
                "warnings": []
            }