# 三套存储（已按问答调整）

车间事实用 **两套 PostgreSQL** 分开扛量；项目配置用 **SQLite**（与旧 `sfc-crawler` 的配置库同一思路）。

## 怎么切

| 库 | 引擎 | 内容 | 谁写 |
| --- | --- | --- | --- |
| `lim_meta` | **SQLite**（WAL） | 项目/账号/SSO/字段映射/权限/同步摘要日志/FACA 单据 | API、采集写日志 |
| `lim_raw` | **PostgreSQL** | 仅爬取原始数据（ODS），按 SN 覆盖 | 仅 Collector |
| `lim_dwh` | **PostgreSQL + Timescale** | 清洗后明细 DWD、汇总 ADS | 仅 Processor |

应用三套连接：`get_meta_db()` / `get_raw_db()` / `get_dwh_db()`。禁止跨库 JOIN。

`lim_raw` 与 `lim_dwh` 使用 **两个独立 Postgres 实例**（两个容器），不是同一实例上的两个 database。

## 元数据为什么用 SQLite 够用

配置不频繁改、体量小，旧爬虫已经用 SQLite 管 SSO、账号池、项目表。单机/Compose 挂一份文件即可。

**项目元数据只在 SQLite**：表 `meta_projects`、`meta_settings`。增删改走 API，没有 YAML 配置文件。

注意：

- 打开 **WAL** + `busy_timeout`，避免 API 和采集同时写锁死。
- 同步日志只存摘要（时间、行数、成功/失败），不要把整份 CSV 塞进 SQLite。
- 文件放 `data/meta/lim_meta.sqlite`，备份就是拷这个文件。
- 以后若多机部署或日志暴涨，再把 meta 迁 Postgres，接口不变。

## `lim_raw`（原始）

- 一项目可以一张动态宽表或统一 ODS + `raw_json`（实现时再定，原则是 Collector 只碰这个库）。
- 默认 SN 唯一、整行覆盖。
- 不在这里做分析查询（最多对账、重跑）。

## `lim_dwh`（处理后）

- Processor 从 raw 读、写入 DWD/ADS。
- 前端分析、异常、柏拉图只打这个库。
- Timescale 用在带时间的明细/汇总。

## FACA

单据量远小于测量流水，**默认跟配置一起放 SQLite**。用 `project_id` + SN 引用 raw/dwh，不把测量行拷进 FACA 表。

## 数据流

```
配置 ← SQLite lim_meta
SFC CSV → data/raw/ 落地
       → 成功写入 PostgreSQL lim_raw 后立即删文件
       → 失败则保留文件，摘要日志写 SQLite
lim_raw → Processor → PostgreSQL lim_dwh（DWD/ADS）
API：读 dwh 做分析，读写 sqlite 做配置/FACA/同步状态
```
