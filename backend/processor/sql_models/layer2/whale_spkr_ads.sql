-- analysis 模型: WhaleSpkr
-- 描述: 无
-- 源表(lim_dwh): whale_spkr_dwd
-- 目标表(lim_dwh): whale_spkr_ads
-- 时间字段: ServerTime → hour (hour)
-- 执行: 独立聚合 Worker 在 dwh 跑本 SELECT，写入 ADS
--
WITH aggregated AS (
    SELECT
    date_trunc('hour', "ServerTime") AS "hour"
    FROM "whale_spkr_dwd"
    WHERE "ServerTime" IS NOT NULL
    GROUP BY date_trunc('hour', "ServerTime")
)
SELECT
    aggregated.*,
    NOW() AS etl_at
FROM aggregated
ORDER BY "hour" DESC
