-- analysis 模型: EagleRcvr
-- 描述: project=eagle_rcvr
-- 源表(lim_dwh): eagle_rcvr_dwd
-- 目标表(lim_dwh): eagle_rcvr_ads
-- 时间字段: ServerTime → hour (hour)
-- 执行: 独立聚合 Worker 在 dwh 跑本 SELECT，写入 ADS
--
WITH aggregated AS (
    SELECT
    date_trunc('hour', "ServerTime") AS "hour",
    "自动外观线体" AS "自动外观线体",
    "机台" AS "机台",
    "本体" AS "本体",
    "模穴" AS "模穴",
    "模仁" AS "模仁",
    COUNT("排次总结果") AS "注塑机总产量",
    SUM("排次总结果") AS "注塑机总不良数",
    COUNT("外观总结果") AS "自动外观总产量",
    SUM("外观总结果") AS "自动外观总不良数",
    SUM("外长直边") AS "外长直边不良数",
    SUM("正面硅胶") AS "正面硅胶不良数",
    SUM("内长直边") AS "内长直边不良数",
    SUM("反面烟囱") AS "反面烟囱不良数",
    SUM("正面支架") AS "正面支架不良数",
    SUM("反面边框") AS "反面边框不良数",
    SUM("硅胶短边") AS "硅胶短边不良数",
    SUM("B5合模线溢胶") AS "B5合模线溢胶不良数",
    SUM("B1缺胶气泡") AS "B1缺胶气泡不良数",
    SUM("B2凹坑") AS "B2凹坑不良数",
    SUM("底涂") AS "底涂不良数",
    SUM("硅胶") AS "硅胶不良数",
    SUM("定位") AS "定位不良数"
    FROM "eagle_rcvr_dwd"
    WHERE "ServerTime" IS NOT NULL
    GROUP BY date_trunc('hour', "ServerTime"), "自动外观线体", "机台", "本体", "模穴", "模仁"
)
SELECT
    aggregated.*,
    NOW() AS etl_at
FROM aggregated
ORDER BY "hour" DESC
