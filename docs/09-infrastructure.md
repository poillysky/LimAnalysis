# 中间件 / 基础设施对照

## 已记：现在不上，后面再说

稳定性先靠：**SQLite + 两个独立 Postgres、备份、采集可重跑、同时只跑一轮**。

**现在不配：** Redis、Celery/Kafka、MinIO、ES。  
**后面再议的触发条件：** 采集/API/处理拆成多进程抢任务、或大屏把 PG 打满需要缓存。到时候再加 Redis，并做成可配置、可关掉。

---

对照 `refence/legacy-src` 三个旧服务 + 当前 LimAnalysis 已拍板存储。这里的「中间件」指 Redis、库、队列等，不是 FastAPI 的 HTTP middleware。

## 旧项目实际用了什么

| 组件 | sfc-crawler | etl-app | lqins | 说明 |
| --- | --- | --- | --- | --- |
| SQLite | 配置库 | 配置库 | 业务+配置 | 三套都有 |
| MySQL | 原始 CSV 入库 | ETL 读写事实表 | 无 | 大批量走 MySQL |
| Redis | **未进依赖**；测试脚本曾读配置，引擎里已无实现 | 无 | 无 | 不要当「现成项目在用 Redis」 |
| Celery / RabbitMQ / Kafka | 无 | 无 | 无 | 爬虫注释写明用 APScheduler **替代 Celery** |
| 调度 | APScheduler（进程内） | `schedule` | APScheduler | 都是进程内定时 |
| 采集 HTTP | `requests`（SSO+下载） | 无爬虫 | 无 | 不是 Playwright |
| 对象存储 / MinIO | 无 | 无 | 本地磁盘图片 | |
| Nginx | 还原后端时已去掉 | 无 | gunicorn | |

结论：旧栈是 **SQLite 配置 + MySQL 大数据 + 进程内定时**，没有消息队列，没有真正落地的 Redis。

## 新平台应对（已拍板）

MySQL 换成两套独立 PostgreSQL；配置仍 SQLite。

| 组件 | 框架阶段 | 采集/分析做起来之后 | 不要现在加 |
| --- | --- | --- | --- |
| **SQLite** | 要 | 项目/账号/同步摘要/FACA | |
| **PostgreSQL `lim_raw`** | 要（独立容器） | ODS | |
| **PostgreSQL `lim_dwh`** | 要（独立容器） | DWD/ADS；镜像可再换成 Timescale | |
| **TimescaleDB** | 可晚些 | 时序明细变大再换 dwh 镜像 | 现在普通 PG 即可 |
| **APScheduler** | 采集开工时加 | 10 分钟一轮、进程内 | Celery |
| **Playwright 或 requests** | 采集开工时定 | 旧逻辑是 requests+SSO；页面复杂再上 Playwright | |
| **Nginx** | 部署前端+API 时 | 反代、静态资源 | 开发期 Vite 代理即可 |
| **磁盘 `data/raw`** | 要 | CSV 落地、可重跑 | MinIO（除非图片量很大、多机） |
| **Redis** | 不需要 | 多进程抢任务锁、分布式 Session、热缓存再加 | 现在加是空转 |
| **Celery / Redis Queue / Kafka** | 不需要 | 任务变成很多、要独立 worker 再考虑 | 两项目 10 分钟一轮用定时器够 |
| **Prefect** | 后期 | 设计报告里的调度升级 | 框架期 |
| **MySQL** | 不要 | 已被 PG 替代 | 再引入第三套关系库 |
| **Elasticsearch** | 不要 | ADS 预聚合即可 | |
| **企业微信机器人** | 已定为后期 | 先日志+页面 | |

## 开发机 Compose 最小集

现在 `deploy/docker-compose.yml` 只有：

1. `postgres-raw`
2. `postgres-dwh`

SQLite 是文件，不进 Compose。不要为「看起来完整」加 Redis。

## 以后加 Redis 的明确信号

出现下面之一再加，并做成可配置、可关掉：

- API、采集、处理拆成多个进程，需要「同时只跑一轮」的分布式锁
- 多实例登录态 / 限流
- 大屏高频读同一汇总，PG 被打满

## 采集实现时再装的库（不是中间件）

`apscheduler`、`pandas`、`requests` 或 `playwright`、`cryptography`（账号加密，旧爬虫有）。
