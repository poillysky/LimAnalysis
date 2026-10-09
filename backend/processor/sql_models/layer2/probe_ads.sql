-- analysis 模型: t
-- 描述: 无
-- 源表(lim_dwh): s
-- 目标表(lim_dwh): probe_ads
-- 时间字段: t → hour (hour)
-- 执行: 独立聚合 Worker 在 dwh 跑本 SELECT，写入 ADS
--
WITH aggregated AS (
    SELECT
    date_trunc('hour', "t") AS "hour",
    COUNT(*) AS "c"
    FROM "s"
    WHERE "t" IS NOT NULL
    GROUP BY date_trunc('hour', "t")
)
SELECT
    aggregated.*,
    NOW() AS etl_at
FROM aggregated
ORDER BY "hour" DESC
