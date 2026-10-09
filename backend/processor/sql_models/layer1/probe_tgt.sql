-- link 模型: t
-- 描述: 无
-- 源表(lim_raw): s
-- 目标表(lim_dwh): probe_tgt
-- 唯一键: 无
-- 执行: Worker 在 raw 跑本 SELECT（增量时按 ingested_at 过滤），再写入 dwh
--
SELECT
    NULLIF(BTRIM(("a")::text), '') AS "a",
    NOW() AS etl_at
FROM "s"
