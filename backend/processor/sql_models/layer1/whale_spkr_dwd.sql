-- link 模型: WhaleSpkr
-- 描述: 无
-- 源表(lim_raw): whale_spkr_raw
-- 目标表(lim_dwh): whale_spkr_dwd
-- 唯一键: FCoverSN
-- 执行: Worker 在 raw 跑本 SELECT（增量时按 ingested_at 过滤），再写入 dwh
--
SELECT
    NOW() AS etl_at
FROM "whale_spkr_raw"
