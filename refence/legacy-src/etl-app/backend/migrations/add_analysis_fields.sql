-- 添加分析表相关字段的数据库迁移脚本
-- 执行时间: 2024-01-15

-- 1. 在 etl_models 表添加分析表时间聚合配置字段
ALTER TABLE etl_models 
ADD COLUMN IF NOT EXISTS time_field VARCHAR(100) COMMENT '时间字段名（用于聚合）',
ADD COLUMN IF NOT EXISTS granularity VARCHAR(20) DEFAULT 'hour' COMMENT '聚合细度(hour/day/week/month)',
ADD COLUMN IF NOT EXISTS time_field_name VARCHAR(100) DEFAULT 'hour' COMMENT '生成的时间字段名';

-- 2. 在 etl_model_fields 表添加字段类别和聚合函数字段
ALTER TABLE etl_model_fields 
ADD COLUMN IF NOT EXISTS field_category VARCHAR(20) COMMENT '字段类别(dimension/measure/derived)',
ADD COLUMN IF NOT EXISTS aggregate_func VARCHAR(50) COMMENT '聚合函数简写(用于前端)';

-- 3. 更新现有数据的默认值
UPDATE etl_models 
SET granularity = 'hour', time_field_name = 'hour' 
WHERE model_type = 'analysis' AND granularity IS NULL;

-- 4. 验证字段是否添加成功
SELECT 
    COLUMN_NAME, 
    DATA_TYPE, 
    COLUMN_DEFAULT, 
    COLUMN_COMMENT 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_NAME = 'etl_models' 
AND COLUMN_NAME IN ('time_field', 'granularity', 'time_field_name')
ORDER BY ORDINAL_POSITION;

SELECT 
    COLUMN_NAME, 
    DATA_TYPE, 
    COLUMN_DEFAULT, 
    COLUMN_COMMENT 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_NAME = 'etl_model_fields' 
AND COLUMN_NAME IN ('field_category', 'aggregate_func')
ORDER BY ORDINAL_POSITION;
