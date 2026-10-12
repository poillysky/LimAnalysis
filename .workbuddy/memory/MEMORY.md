# LimAnalysis 项目长期记忆

## 一、环境事实（本机，2026-10-06 实测）

### Docker 与本机数据库
- **本机没有安装 Docker**（全盘找不到 `docker.exe`，PATH 里也没有）
- **但本地开发不需要它**：`backend/.env` 里三套库全指向 **NAS**，不是本地容器
  - `RAW_DATABASE_URL`    → `192.168.2.38:15432/lim_raw`
  - `DWH_DATABASE_URL`    → `192.168.2.38:15433/lim_dwh`
  - `DEFECT_DATABASE_URL` → `192.168.2.38:15434/lim_defect`
- `deploy/docker-compose.yml`（本地 5432/5433/5434）目前**用不上**；
  `deploy/docker-compose.nas.yml` 是 NAS 上跑的（15432–15434 + Adminer 18080 + Metabase 13000）
- 元数据 SQLite 在仓库内：`data/meta/lim_meta.sqlite`（已被 .gitignore 排除）

### 本机工具链
- 托管运行时：Python 3.13.12（managed）/ 3.12.7（system）；Node 22.22.2 / 24.13.0
- **后端用 `backend/.venv`**（Python 3.12），依赖在 `backend/requirements.txt`
- 前端用 **pnpm**（`C:\Users\poilly\AppData\Roaming\npm\pnpm`），lock 文件是 `pnpm-lock.yaml`
- **本机没有 `make`** —— 任务入口一律用 Python 脚本（如 `scripts/check.py`）
- **本机没有 `pytest`** —— 测试用标准库 `unittest`
- ruff 已装（0.16.10），配置在 `backend/pyproject.toml`

### 网络（重要）
- `pip.ini` 里配的代理是 `http://127.0.0.1:7897`（用户自己的，可用）
- **但会被 WorkBuddy 注入的 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:61513` 覆盖**，
  那个端口不通 → pip 静默挂起 / SSLEOFError
- 装包优先 **清华镜像 + 直连**（实测 4 MB/s，比走代理快约 300 倍）
- 详见技能 `cn-python-pkg-behind-proxy`

## 二、本地启动方式

### 后端（端口 8000）
```bash
cd backend
HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= \
  .venv/Scripts/python.exe -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  --reload-dir app --reload-dir collector --reload-dir processor
```
清空代理环境变量是为了让 app 内的 HTTP 客户端（SFC 抓取 / Metabase 探测）
不走那个坏代理。psycopg 连 NAS 走原生 socket，不受代理影响。

### 前端（端口 8848）
```bash
cd frontend && pnpm dev
```
- `VITE_PORT = 8848`、`VITE_PROXY_TARGET = http://127.0.0.1:8000`（在 `.env.development`）

### 健康检查
```bash
curl --noproxy '*' http://127.0.0.1:8000/api/health          # {"success":true,...}
curl --noproxy '*' http://127.0.0.1:8848/api/health          # 经 vite proxy 透传
```
> **curl 一定要加 `--noproxy '*'`**：本机环境变量里有坏代理，
> 不加会得到 `502` 或 `000`，误判成服务没起来。

## 三、约定与坑

### 前端 package.json 脚本必须跨平台
- 原写法 `"dev": "NODE_OPTIONS=--max-old-space-size=4096 vite"` 是 **Unix 语法**，
  Windows 的 cmd.exe 不认，报 `'NODE_OPTIONS' 不是内部或外部命令`
- 已改为 `node --max-old-space-size=4096 node_modules/vite/bin/vite.js`（语义等价、零新依赖）
- **新增脚本时不要再用 `VAR=值 cmd` 前缀**；要设环境变量就装 `cross-env`，
  或改用 node 的 CLI 参数

### Windows / Git Bash 环境
- `/tmp` 在 bash 与 Python 之间**不一致**（bash 的 `/tmp` → Python 眼里是 `E:\tmp`）。
  统一用 `C:/Users/poilly/AppData/Local/Temp/` 或项目内 `.tmpdl/`（已 gitignore）
- Git Bash 常缺基础命令，脚本开头加
  `export PATH="/usr/bin:/bin:/usr/local/bin:$PATH"`
- `tasklist` / `wmic` 加 `MSYS_NO_PATHCONV=1` 才不被路径转换搞坏
- `taskkill` 在沙箱里会被拒（拒绝访问）；**用 PowerShell 的 `Stop-Process -Id X -Force` 可以**
- PowerShell 工具在本环境**不回显 stdout** —— 要拿结果就用 Bash 侧的命令验证

### 导入冒烟测试必须排除 `__main__.py`
`collector/__main__.py` 模块级就是 `raise SystemExit(main())`，
import 它等于**真的启动 worker + 调度器**。已踩过一次（幸好 `is_active` 默认 False 未产生副作用）。

### 数据库 schema 变更
`app/core/meta_init.py` 的 `MetaBase.metadata.create_all(meta_engine)`
**只建新表，不给已存在的 SQLite 表补列**。加字段必须配手写 `ALTER TABLE`。

### 架构约束
`app/core` 是最底层，**不允许** import `collector` / `processor`。
SQL 标识符工具在 `app/core/sql_ident.py`（零依赖，只准 `import re`）。
任务类型/状态**纯常量**在 `app/core/job_types.py`（`collector/jobs.py` re-export）；
队列操作函数（enqueue/claim/finish/prune）留在 `collector/jobs.py`，
`app/core/disk_cleanup.py` 里对它们的调用是**函数内延迟导入**，已登记进守卫的
`ALLOWED_DEFERRED`（无加载期倒挂）。
由 `tests/test_arch_guard.py` 三条用例强制守卫。

### 鉴权模型（2026-10-10 起）
- 所有业务路由**默认要求登录**：`app/api/router.py` 统一挂 `Depends(require_user)`。
- 豁免仅 4 个：`/auth/login`、`/auth/refresh-token`、`/auth/routes`、`/api/health`。
- `app/api/deps.py`：`require_user`（HTTPBearer）/ `require_admin`（403）。
- 敏感接口（用户管理、连接配置、磁盘清理、清空表）额外 `require_admin`。
- 新增受保护接口**无需**手写鉴权，自动继承（除非显式豁免）。
- 默认管理员口令：首次启动**随机生成并打印一次**；`LIM_INITIAL_ADMIN_PASSWORD` 可指定。

### 日志
统一标准库 logging，集中配置 `app/core/log_setup.py#setup_logging()`（幂等），
API 与两个 worker 入口调用；`LIM_LOG_LEVEL` 调级别。**不引入 Loguru。**

## 四、检查入口

```bash
cd backend && HTTP_PROXY= HTTPS_PROXY= .venv/Scripts/python.exe scripts/check.py  # lint + 测试
cd backend && HTTP_PROXY= HTTPS_PROXY= .venv/Scripts/python.exe scripts/check.py lint    # 只 lint
cd backend && HTTP_PROXY= HTTPS_PROXY= .venv/Scripts/python.exe scripts/check.py test    # 只测试
```
- 当前基线（2026-10-12 晚 刷新）：**ruff 0 问题 / 243 个 unittest 全过**
  （2026-10-10 记的 179、当日下午记的 230 均已过时 —— 新增 `tests/test_metabase_embed.py` 13 个。
  注意：2026-10-12 之前 `check.py` 其实是**红的** ——
  `app/main.py` 导入顺序 + `test_column_map.py` / `test_sn_column.py` 的 RUF012/SIM117，
  同日已修。**不要相信"上次是全绿的"，跑一遍再下结论。**）
- 前端：
  - `pnpm typecheck:strict` —— **业务 0 错 / 模板层 414（基线 415）**
  - `pnpm verify:css <改前目录> <改后目录>` —— CSS 产物规则级比对（忽略顺序、归一化 scoped hash）
  - `pnpm verify:dedup` —— **当前跑不起来**，见下方遗留
- **跑起来 ≠ 生效**：本机后端不一定带 `--reload`。改了路由后用
  「新路由返回 404、已存在路由返回 401」来判别是否需要重启（PID 4020 / :8000 曾未重载）。

## 四·二、数据浏览（功能管理 → 数据浏览）约定

- 接口前缀 `/api/v1`（写 `/api/...` 会 404）；`/api/v1/system/db/{target}/...`，
  target ∈ `meta | raw | dwh | defect`。
- **筛选参数统一是 `filters`，值为 JSON 字符串**，如
  `?filters={"project_id":"eagle_rcvr","defect_item":"烟囱溢胶"}`，按等值 AND。
  新增可筛选维度时：前端往 `FILTER_DIMS` 加一项即可，**列的筛选值域由
  `/tables/{table}/values?column=..` 从真实数据取**，不写死枚举。
- 核心在 `app/core/db_browser.py`：`normalize_filters` / `_eq_clause` /
  `_time_clause` / `_where_clause`（预览与导出共用同一套 WHERE，别再各写一份）。
- 两条刻意的行为，别"顺手优化"掉：
  1. **未知列报错而不是忽略** —— 静默忽略会导出"看着对、实则没筛"的数据。
  2. 下载时「无时间范围且无任何筛选」才拒绝 —— 这是防误点拉整表的保护。
- 页面 `views/feature/db-browser.vue` 的筛选条只在**当前表真有该列**时渲染。


## 四·三、看板 iframe 地址的来源（2026-10-12 改）

- 看板页 `views/exception/monitor/index.vue` 的 `<iframe :src>` **完全来自后端**
  `GET /api/v1/system/metabase/board` 返回的 `current.embed_url`，前端不做任何拼接。
- 后端 `app/core/metabase_embed.py#board_for_project(project_id, board, request_host)`：
  用「外部连接」里那**一个** Metabase 地址做**服务端**调用（登录 / 列画布 / 开嵌入），
  但下发 `embed_url` 时把**主机名换成浏览器当前用的主机**（协议与端口沿用配置），
  由 `_embed_base()` 实现。**NAS 双网口（办公网 / 生产网）就靠这个自动适配**，
  不需要（也无法）在配置里填两个 IP —— 那个字段只有一个。
- 开关：环境变量 `LIM_MB_EMBED_FOLLOW_HOST`（默认开；置 `0` 退回写死地址）。
- 因此「外部连接」里的地址**只需服务端可达**即可（如 `http://192.168.2.38:13000`
  或容器内的 `http://host.docker.internal:13000`），浏览器侧会自动跟随。
- 改这里要**重新构建镜像**（`deploy/docker-compose.limana.yml` 用的是
  `poillysky/limanalysis:V1.0.x` 预构建一体镜像）。
- 遗留：`views/feature/connections.vue` 的「打开 Metabase」按钮仍直接用配置地址
  `window.open(metabaseUrl)`，生产网下点它会打不开（页面本身不受影响）。

## 五、已知遗留

- 测试覆盖仍偏薄（多数业务模块无测试）；`processor/agg_executor.py` / `collector/runner.py`
  等关键路径仍无隔离测试。`app/api/deps.py`（鉴权）与 `inspection_parts` 本次已补测。
- 无 CI（`.github/workflows` 不存在），上述命令仍需人肉记得跑
- `deploy/docker-compose*.yml` 里 `POSTGRES_PASSWORD: lim` 是硬编码明文
- 前端模板层还有 414 个 strict 类型错误（基线 415，只准降不准升）待逐步消
- **`pnpm verify:dedup` 已失效**：它要读外部 `LIM_SNAP_DIR` 快照目录，
  而那是阶段一的一次性产物（临时目录已清理）。要么重建快照，
  要么把脚本改成自包含（把旧实现内联进去，不依赖外部快照）。
- 其他偏大文件（本次未拆，可后续按同样手法处理）：
  `app/core/ads_query.py`(785) / `defect_store.py`(725) / `disk_cleanup.py`(714) /
  `appearance_index.py`(662) / `processor/models_store.py`(616)。

## 六、样式相关约定

- 页面的 `<style>` 外移到 `<页面名>.styles/` 目录，用 `@use "..." as *` 引入
  （**不要再用 `@import`**，Dart Sass 3.0 会移除它）
- `popper.scss` 这类需要 teleport 到 body 的样式必须放**非 scoped** 的 `<style>` 块
- 改任何 `<style>` 内容都会让 Vue 的 scope id（`data-v-xxxxxxxx`）变化，
  CSS 与 JS 产物文件名随之改变 —— 属正常，但要确认两侧一致
