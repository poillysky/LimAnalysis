# 问答记录

一次一问。未写入本文件的仍算未确认。

## Q1 第一期项目清单

**结论：** 先用两个项目做测试，都启用。

| project_id | 显示名 | sfc_code（p） | type | 样本 |
| --- | --- | --- | --- | --- |
| `eagle_rcvr` | EagleRcvr | `SFCEagleRcvr` | `0` | `refence/legacy-src/SFCEagleRcvr_all_*.csv` |
| `whale_spkr` | WhaleSpkr | `SFCWhaleSpkr` | `0` | `refence/legacy-src/SFCWhaleSpkr_all_*.csv` |

默认：`sfc_code = SFC{显示名}`（已带 `SFC` 则不重复加），`btype = 0`，`prefix = project_id`。可改；后续加项目只加配置，不改表结构。

## Q2 CSV 种类

**结论：** 每个项目只有 **一种导出、一张宽表**。外观测量与注塑相关字段已经合并在同一 CSV 里，不另拉注塑文件。入库按「一项目一 ODS 源」即可，字段差异用配置 + `raw_json`。

## 核心规则：可配置，禁止硬编码

项目侧所有行为（同步间隔、全量/增量、重试、字段映射、启用开关、唯一键策略等）必须能在 **元数据库 / 项目配置** 里改，代码里只允许 **默认值**，不允许写死某个项目或某个间隔。

加新项目 = 加配置，不改采集/处理代码。

## Q3 同步频率与窗口

**结论：** 不写死。默认沿用旧系统经验值，均可在项目配置里改：

| 项 | 默认（可改） |
| --- | --- |
| 间隔 | 10 分钟 |
| 范围 | 全量（`*_all_*`） |
| 入库 | 按配置的唯一键覆盖/插入 |
| 重试 | 3 次 |

## Q4 唯一键默认策略

**结论：** 默认按 **SN** 唯一（CSV 第一列，样本为 `FCoverSN`），同一 SN 重复则 **覆盖整行**。各项目可在配置里改唯一键，代码不写死列名。

## Q5 登录 SFC

**结论：** 与参照项目 `sfc-crawler` 一致，地址和账号全部进配置。

- 全局配置：SSO 地址、SFC 基址、登录路径、数据路径、Line/Section 等
- **账号池**：多账号、加密存储、按优先级尝试；账号错误换下一个；超时/限流可重试
- 登录：SSO POST（`txtUserNo` / `txtPass`）→ ValidateTaken → 校验 SFC Session → 再下载 CSV
- 下载：`sfc_data_path?p={sfc_code}&&type={btype}`（每项目可配）

## Q6 失败通知

**结论：** 第一期只做 **同步日志 + 页面状态**。告警通道（企微/钉钉）预留配置位，本期不接机器人。

## Q7 存储划分

**结论：** 同意三套存储。

| 用途 | 引擎 |
| --- | --- |
| 元数据（配置、账号、权限、同步摘要、FACA） | SQLite + WAL |
| 爬取原始（大量） | PostgreSQL `lim_raw` |
| 处理后分析（大量） | PostgreSQL `lim_dwh` + Timescale |

## Q8 两套 PostgreSQL 部署

**结论：** **两个独立 Postgres 容器/实例**（`lim_raw` 与 `lim_dwh` 物理隔离）。SQLite 仍为本地文件。

## Q9 测试阶段优先场景

**结论：** **暂缓**，做到那一块再定。骨架先按可配模块预留：同步监控、柏拉图、NG 列表、宽表字段对比，不在现在砍范围。

## Q10 车间大屏及其它细节

**结论：** 不急。先搭框架；大屏、柏拉图字段、sfc_code 等 **做到那块再问**。

## 项目元数据存放

**结论：** 项目元数据只在 **SQLite**。用管理接口增删改，**不再使用 YAML 配置文件**。

## 中间件（Redis 等）

**结论：** 现在只保留 SQLite + 两个独立 PG。Redis / 队列 / MinIO **后面再说**。触发：多进程抢任务或查询把 PG 打满。详见 `09-infrastructure.md`。

## CSV 落地与删除

**结论：** 采集 CSV 先落到 `data/raw/`。**成功写入 `lim_raw` 后立即删除该文件。** 失败或未完成则保留，便于重试和对账。

## Q11 车间离线

**结论（已更新）：** 不再用 `WORKSHOP_OFFLINE` 限制功能。SFC / AI / 公式等是否可用，只看各自配置与网络是否通。前端打包仍建议自包含（`VITE_CDN=false`），避免依赖公网静态资源。



## Q12 鉴权模型（2026-10-10 补齐）

**背景：** 功能基本完成后做架构复盘，发现后端 131 个路由**全部无鉴权**：
`app/core/tokens.py` 有签发/解析能力，但只有 `/auth/refresh-token` 用到；
前端 `utils/http` 早已在自动附 `Authorization`。属"登录有壳、接口裸奔"。

**结论：** 统一鉴权落地。
- 默认全量保护：`app/api/router.py` 为所有业务路由挂 `Depends(require_user)`。
- 豁免：`POST /auth/login`、`POST /auth/refresh-token`、`GET /auth/routes`、
  `GET /api/health`；以及 `GET /inspection/image`（见下条，用短时票据自证，不是裸奔）。
- **图片 URL**：`<img src>` 无法带 `Authorization`。列表接口签发绑定 `source+rel` 的
  HMAC 短时 `ticket`（`tokens.issue_media_ticket`），图片路由校验票据，不走 Bearer。
- 角色：`require_admin` 用于用户管理、项目增删改、连接配置/探测、磁盘清理、
  清空表、CSV 导出等敏感操作。`common` 访问上述接口返回 403。
- 令牌：沿用自研 HMAC-SHA256（`tokens.py`），无第三方依赖；前端 `Bearer ` 前缀兼容。
- **默认口令变更**：`seed_default_admin()` 不再硬编码 `admin123`。首次启动随机生成并打印一次；
  可用环境变量 `LIM_INITIAL_ADMIN_PASSWORD` 指定初始口令。
- 失败响应统一为 `{success:false,message}` + 401/403，与前端 http 封装约定一致；
  前端对非登录接口的 401 统一 `logOut` 回登录页。
- 覆盖测试：`tests/test_auth_deps.py`、`tests/test_media_tickets.py`。

## Q13 日志与模块拆分（2026-10-10）

**日志：** 统一用标准库 logging，集中配置在 `app/core/log_setup.py`（幂等），
API 与两个 Worker 启动时调用；`LIM_LOG_LEVEL` 可调级别；对 urllib3/requests/apscheduler 降噪。
**不引入 Loguru**（与设计报告原选型不符，已回写 `03`）。

**模块拆分：**
- `app/modules/system/router.py`：668 行 / 53 路由 → `system/routes/` 六个子路由，
  `router.py` 仅做聚合。对外路径与鉴权完全不变（99 接口 / 95 受保护 / 4 豁免，拆分前后一致）。
- `app/core/inspection.py`：1622 行 → 门面 + `app/core/inspection_parts/`
  （browse / dates / filenames / constants）。门面 re-export，既有 import 路径不变。

**架构守卫修复：** `test_arch_guard.py` 此前**已在失败**（非本次引入）：`runtime_status.py`
模块顶层 import `collector.jobs`。修法：把任务类型/状态**纯常量**下沉到 `app/core/job_types.py`，
`collector/jobs.py` re-export；`disk_cleanup.py` 中确实需要 Worker 层的队列操作函数
（enqueue/find/prune）登记进守卫的 `ALLOWED_DEFERRED`（函数内延迟导入，无加载期倒挂）。

**测试隔离：** `tests/test_defect_scan_upload.py` 原为裸函数（`unittest discover` 根本收集不到），
且直连真实 NAS 库。已重写为 `unittest.TestCase` + `unittest.mock`，桩掉项目查询与写库，不碰任何 DB。
