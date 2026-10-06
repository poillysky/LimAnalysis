# 已确认底线

来源：[03-design-report-v1.md](./03-design-report-v1.md) + 此前「两套 Postgres、FastAPI、Pure Admin 精简版」约束。

## 产品

- 名称：车间异常与不良分析平台（含 FACA），仓库名 LimAnalysis。
- 目标：本地掌控 SFC 导出数据；准实时异常；多维不良分析；工艺关联；FACA 基础闭环。
- 约束：当前 **没有 SFC 正式 API**，只能走网页导出 CSV；多项目并行；分钟级准实时，不是毫秒级。

## 技术

| 项 | 结论 |
| --- | --- |
| 后端 | FastAPI，Python 3.11+，模块化单体 |
| 前端 | Vue3 + Element Plus（本仓库已用 Pure Admin 精简版）。报告 Phase 1 曾写 Streamlit，**不采用**，避免两套 UI |
| 采集 | Playwright 定时拉 CSV（独立 Collector，只写 ODS） |
| 调度 | 前期 APScheduler，后期可换 Prefect |
| 数据库 | **SQLite 元数据** + **PG 原始库** + **PG 处理后库（Timescale）**。见 `04-two-database.md` |
| 数据分层 | `lim_raw` = ODS；`lim_dwh` = DWD/ADS；配置在 SQLite |
| 扩展 | 新功能以新增模块 / 表 / 任务为主 |
| 部署 | **离线车间**（现场不联网）。Compose 起两个独立 PG 容器 + SQLite 文件卷。业务数据必须提前下载入库。见 `07-qa-log.md` Q11 |

## 建设范围（当前阶段）

做：CSV 采集、本地仓、不良分布、异常监控、基础关联、可视化查询、FACA 基础、多项目配置与同步日志、基础权限。

后做：高级 SPC、智能根因、完整规则引擎、完整 8D、移动端。

## 核心规则：可配置，禁止硬编码

项目差异（间隔、全量/增量、字段、唯一键、是否启用等）全部进 SQLite。代码只提供默认值。新项目走管理接口，不改代码。详见 `07-qa-log.md`。

## 本阶段纪律

实现采集/处理前先确认 `05`。目录规范以 `06` 为准。
