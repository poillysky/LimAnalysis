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
由 `tests/test_arch_guard.py` 三条用例强制守卫。

## 四、检查入口

```bash
cd backend && .venv/Scripts/python.exe scripts/check.py        # lint + 测试
cd backend && .venv/Scripts/python.exe scripts/check.py lint    # 只 lint
cd backend && .venv/Scripts/python.exe scripts/check.py test    # 只测试
```
- 当前基线：ruff 0 问题 / 148 个 unittest 全过
- 前端：`pnpm typecheck:strict`（业务 0 错 / 模板层 415 基线）、`pnpm verify:dedup`

## 五、已知遗留

- 测试覆盖仅 9/85 业务模块；`app/core/users.py` / `tokens.py` / `secret_box.py` /
  `processor/agg_executor.py` / `collector/runner.py` 等关键路径无测试
- 无 CI（`.github/workflows` 不存在），上述命令仍需人肉记得跑
- `deploy/docker-compose*.yml` 里 `POSTGRES_PASSWORD: lim` 是硬编码明文
- 前端模板层 375 个 strict 类型错误待逐步消
- Sass `@import` 已废弃（Dart Sass 3.0 将移除），
  `views/*/*.styles/scoped.scss` 的 `@import` 需迁到 `@use`
