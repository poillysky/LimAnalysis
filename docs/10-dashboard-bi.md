# 数据看板实现方案（ADS + Metabase）

目标：侧边栏「数据看板」一项目一张画布；数字来自已算好的 ADS（每小时一行组合）；图表以柱状图为主；近 3 小时看整体，不按小时拆开展示。

结论先说：**不要改 ADS 粒度，也不要看板再扫 DWD。** ADS 表本身类型正确；`lim_dwh` 上只维护一个近 3 小时宽表视图给 Metabase；LimAnalysis 用 iframe 按项目嵌入对应 Dashboard。

---

## 1. 已有数据

- 库：`lim_dwh`（PostgreSQL）
- 表：`{项目前缀}_ads`，如 `eagle_rcvr_ads`
- 粒度：`hour × 自动外观线体 × 机台 × 模穴 × 模仁` 一行
- 度量：产量、不良数为 **计数/求和后的绝对值**（注塑机总产量、注塑机总不良数、自动外观总产量、自动外观总不良数，以及各不良项 `*不良数`）
- 类型：写入与存量迁移保证 `hour`/`etl_at` 为 `timestamptz`，`*产量`/`*不良数`/`*不良率`/`*良率` 为 `numeric`

看板 **禁止** 对「每小时的不良率」再平均。近 3 小时必须：

```
不良率 = SUM(3小时不良数) / SUM(3小时产量)
良率   = 1 - 不良率
```

---

## 2. 推荐架构

```
lim_dwh.{prefix}_ads          ← 聚合 Worker 按小时写入（timestamptz + numeric）
        ↓
lim_dwh.v_{prefix}_ads_3h     ← 唯一 BI 视图：相对 max(hour) 的近 3 个整点桶
        ↓
Metabase（只读连 lim_dwh，只连 3h 视图）
        ↓ iframe（项目参数 / 不同 Dashboard ID）
LimAnalysis「数据看板」页
```

| 层 | 职责 | 不做什么 |
| --- | --- | --- |
| ADS 表 | 小时事实，Worker 增量回算；类型正确 | 不存率、不改成 3 小时粒度 |
| 3h 视图 | 相对数据最新 hour 的近 3 小时切片 | 不改形状、不做类型补丁 |
| Metabase | 加总、除法、柱状图；宽表多度量 | 不连 DWD/RAW；不依赖 typed/long 补丁视图 |
| 本系统页 | 选项目、嵌画布、登录入口 | 不自己算率 |

Metabase 比自研格子页更合适的原因：要按线体、机台、模穴、不良项多切面下钻，成熟 BI 的筛选和柱图现成。本系统只做「一项目一画布」的壳。

数据层：DWD/ADS 写入即用真实类型（timestamptz / numeric / smallint）；聚合 SQL 对度量直接 `SUM(列)`，不再 `::numeric` 补丁；只维护 `v_{前缀}_ads_3h`。旧的 `ads_typed` / `defect_long` 补丁视图在刷新时 DROP。

公式助手：清洗页按 RAW 文本生成（空串/`'0'`/`'1'`）；聚合页按已类型化 DWD 生成（`IS NULL`、`= 0`/`= 1`）。

---

## 3. 「近 3 小时」口径（必须按数据时间，不要按墙上时钟）

车间 ADS 可能停在几天前。Metabase 默认「过去 3 小时」相对 **现在**，会得到空图。

统一口径：

```
锚点 T = MAX(hour)     -- 该项目 ADS 里最新有数的小时
窗口   = [T - 2 hour, T]  -- 含锚点共 3 个整点桶
```

实现：聚合后自动建视图（见 `processor/ads_bi.py`）：

```sql
CREATE OR REPLACE VIEW v_eagle_rcvr_ads_3h AS
SELECT * FROM eagle_rcvr_ads
WHERE hour IS NOT NULL
  AND hour >= (SELECT max(hour) - interval '2 hours' FROM eagle_rcvr_ads);
```

画布标题可展示实际窗口，例如「2026-07-03 08:00～10:00」，避免误以为是此刻。若以后实时生产跟上，同一视图仍然正确（锚点变成当前小时）。

---

## 4. 指标与分母（先定口径，再画图）

外观相关用 **自动外观总产量** 做分母；注塑/排次相关用 **注塑机总产量**。

| 看板指标 | 分子 | 分母 |
| --- | --- | --- |
| 自动外观总不良率 | SUM(自动外观总不良数) | SUM(自动外观总产量) |
| 自动外观总良率 | 分母 − 分子，或 `1 - 不良率` | 同上 |
| 线体总不良率 | 同上，GROUP BY 自动外观线体 | 同上 |
| 外长直边 / 正面硅胶 / 内长直边 / 反面烟囱 / 正面支架 / 反面边框 / 硅胶短边 | SUM(该项不良数) | SUM(自动外观总产量) |
| 机台不良率 | SUM(自动外观总不良数) 或 SUM(注塑机总不良数) | 对应产量（外观或注塑，全看板选一种并写在图下） |
| B5合模线溢胶 × 模穴 | SUM(B5合模线溢胶不良数) | 建议 SUM(注塑机总产量)（该列来自注塑侧缺陷） |
| B1缺胶气泡 / B2凹坑 | 同 B5 | 注塑机总产量 |
| 底涂 / 硅胶 / 定位 | SUM(该项不良数) | 注塑机总产量（与排次总结果同源字段） |

产量为 0 时率显示空，不要当 0%。

---

## 5. 视图设计（BI 只读这一个）

以下以 EagleRcvr 为例，WhaleSpkr 同样有 `v_whale_spkr_ads_3h`。

### `v_eagle_rcvr_ads_3h`

直接 `SELECT *` 自 `eagle_rcvr_ads`，过滤近 3 小时。列与 ADS 宽表一致：

- `"hour"` → `timestamptz`
- 维度文本：自动外观线体、机台、模穴、模仁
- 所有 `*产量`、`*不良数` → `numeric`

用途：整体 KPI、按线体/机台/模穴，以及各不良项宽列（`外长直边不良数` 等）作度量。

对比多个不良项时：在 Metabase 对宽表选多个度量列，或写一条自定义 SQL 做 unpivot；**不再维护长表视图**。

---

点选建图（不写 SQL）见 [11-metabase-howto.md](./11-metabase-howto.md)。

## 6. Metabase 画布（一项目一 Dashboard）

每个项目一个 Collection + 一个 Dashboard。LimAnalysis 按 `project_id` 打开对应 Dashboard。

建议卡片（全部 **柱状图**，整体良率可用数字卡 + 一根柱）；数据源一律 `v_*_ads_3h`：

1. **近 3 小时 · 自动外观总良率**  
   无分组；表达式 `1 - SUM(自动外观总不良数)/NULLIF(SUM(自动外观总产量),0)`。

2. **近 3 小时 · 各外观线体总不良率**  
   分组：`自动外观线体`；柱 = 不良率。横轴线体。

3. **近 3 小时 · 各线体 × 外观不良项不良率**  
   可视化：分组线体，每个不良项一条「Sum(该项不良数)/Sum(外观产量)」自定义表达式，柱图多度量并排。不要再建 `defect_long`。

4. **近 3 小时 · 各机台不良率**  
   分组：`机台`；口径与第 4 节「机台」一行锁定后写进卡片标题。

5. **近 3 小时 · B5合模线溢胶 · 各模穴不良率**  
   度量：`B5合模线溢胶不良数` / `注塑机总产量`；分组：`模穴`。  
   同结构可复制 B1、B2 等，先做 B5 一张，避免第一版卡片过多。

---

## 7. 嵌进 LimAnalysis

- 路由保持「数据看板」，进入后先选项目（EagleRcvr / WhaleSpkr）。
- 页面主体：Metabase **静态嵌入**（签名 URL）或交互嵌入。第一版用静态嵌入足够：只读、带锁定时间窗。
- 一项目对应一个 `dashboard_id`（存在 SQLite `meta_settings` 或项目 config），不要把连接串写进前端。
- Metabase 只读账号连 `lim_dwh`，不要给 RAW/Meta。

本系统不实现图表引擎；权限以后若要按人，再上 Metabase SSO（交互嵌入，收费）。

---

## 7.1 不花钱（开源版就够）

自建 **Metabase Open Source**，不买 Cloud / Pro / Enterprise。柱状图、SQL、Dashboard、按项目做多张画布 **全部免费**。

嵌进本系统用开源里的 **Guest / 静态嵌入**（JWT 签名 iframe）：只看图、可带筛选，图上会有 “Powered by Metabase”。去掉水印、下钻、按登录人 SSO 才要付费——车间看板用不到。

也可以不嵌：侧边栏「数据看板」直接新窗口打开自建 Metabase。零嵌入、零水印争议。

不要开「公开分享」把 Dashboard 链到公网；车间内网 + 只读库账号即可。

---

## 8. 落地顺序

1. 清洗写入 DWD、聚合写入 ADS 均按字段类型建列；类型不一致时全量重建，不再 ALTER。
2. 聚合后只建 `v_*_ads_3h`，并 DROP 旧 typed/long 视图；度量 SQL 假定 DWD 已是 numeric/smallint。
3. 部署 Metabase，只读连接 `lim_dwh`，同步 3h 视图。
4. 按第 6 节搭 EagleRcvr Dashboard（数据源 `v_eagle_rcvr_ads_3h`）。
5. 数据看板页：项目切换 + iframe。
6. 复制一套给 WhaleSpkr（换表名/Dashboard）。

验收：窗口内产量加总能对上 ADS 三小时 SUM；线体图各柱分母是该线体产量不是全厂产量；不良项图切换线体后分母跟着变；B5 模穴图分母为注塑产量。

---

## 9. 明确不做

- 不把 ADS 改成「3 小时一条」——增量回算、历史小时查询会坏。
- 看板不查 DWD 现场 GROUP BY。
- 不对小时不良率做 AVG。
- 不维护 `ads_typed` / `defect_long` 补丁视图。
- 不用墙上时钟「过去 3 小时」当默认筛选。

---

## 10. 和现有模块的关系

| 模块 | 关系 |
| --- | --- |
| 数据聚合 | 唯一写入 ADS 的来源；写完调用 `ensure_ads_for_metabase` 刷新 3h 视图 |
| 数据清洗 | 看板不读 DWD |
| 数据看板页 | 只嵌 Metabase，不重复实现聚合 SQL |
