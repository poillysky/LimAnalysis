-- 删除 etl_models 表中的 backfill_hours 字段
-- 原因：backfill_hours 应该只在全局配置（etl_config）中配置

ALTER TABLE etl_models DROP COLUMN IF EXISTS backfill_hours;
