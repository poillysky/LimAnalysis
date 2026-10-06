# LimAnalysis

车间异常与不良分析平台。已拍板事项见 `docs/07-qa-log.md`，框架边界见 `docs/08-framework-scope.md`。

## 目录

```
docs/          设计与决策
frontend/      Vue
backend/       FastAPI + collector + processor
data/meta/     SQLite（项目元数据）
data/raw/      CSV 落地
data/raw/      CSV 落地
deploy/        Postgres / 数据浏览（Adminer）容器
```

## 启动

```bash
cd deploy
docker compose up -d
```

NAS 一键（Postgres 15432/15433 + Adminer 18080）：

```bash
cd deploy
mkdir -p /vol1/1000/Docker/LimAnalysis/{lim-raw,lim-dwh,meta,metabase}
docker compose -f docker-compose.nas.yml up -d
```

Adminer：`http://<NAS>:18080`（可嵌前端「数据浏览」；SQLite 路径 `/data/meta/lim_meta.sqlite`）。

Metabase（开源，不收费）：`http://<NAS>:13000`。首次打开设管理员。添加数据库时 Host 填 `postgres-dwh`、端口 `5432`、库名 `lim_dwh`、用户/密码 `lim` / `lim`。图表请用近 3 小时视图 `v_eagle_rcvr_ads_3h`（宽表；ADS 表本身已是 timestamptz/numeric）。

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

**必须开三个后端进程**（API、采集/清洗 Worker、聚合 Worker 分开）：

```bash
# 终端 1：主 API（只接单 / 查状态，不跑爬虫入库）
cd backend
uvicorn app.main:app --reload --port 8000

# 终端 2：采集 / 上传 / 表结构 / 数据清洗
cd backend
python -m collector.worker

# 终端 3：数据聚合（DWD→ADS，可按间隔自动跑）
cd backend
python -m processor.agg_worker
```

Worker 可选：`python -m collector.worker --only crawl`（或 `upload` / `schema` / `etl`）。  
数据清洗（raw→dwh）由采集 Worker 消费 `etl_clean`；数据聚合由独立进程消费 `etl_agg`。

```bash
cd frontend
pnpm install
pnpm dev
```

探测：`http://127.0.0.1:8000/api/health`  
任务状态：`GET /api/v1/sfc/jobs/{id}`  

项目配置在 SQLite。新项目用接口添加，不改代码、不写 YAML：

```http
POST /api/v1/system/projects
{"project_id":"eagle_rcvr","display_name":"EagleRcvr","enabled":true}
```

列表：`GET /api/v1/system/projects`  
默认值：`GET/PUT /api/v1/system/defaults`

Postgres 未启动时 API 仍可起来，health 里 raw/dwh 会显示 degraded。
