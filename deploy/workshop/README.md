# 车间单机部署（离线值守）

目标：一台 Windows 服务器长期跑 LimAnalysis；3～数个浏览器打开页面即可。  
**不要**在车间用 `pnpm dev` / `uvicorn --reload`。

## 架构

| 组件 | 说明 |
| --- | --- |
| Postgres ×3 | 建议 NAS Docker（`deploy/docker-compose.nas.yml`） |
| API | `uvicorn app.main:app` 无 reload |
| collector.worker | 采集 / 上传 / 清洗 / 磁盘清理 |
| agg_worker | DWD→ADS 聚合 |
| 前端 | `pnpm build` 产物 + nginx（或任意静态服务器） |
| Metabase | 可选，局域网；挂了只影响「自动外观数据看板」 |

不引入 Redis/Celery。任务仍走 SQLite `meta_jobs`。

## 一次性准备

1. NAS 起 Postgres（及可选 Metabase）。
2. 车间机：`backend` 建 venv，`pip install -r requirements.txt`。
3. 复制环境变量：
   ```text
   copy deploy\workshop\.env.workshop.example backend\.env
   ```
   改 `CORS_ORIGINS`（车间前端访问地址）、三库 URL；车间建议 `WORKSHOP_OFFLINE=true`。
4. **有网机构建前端**（车间可断公网）：
   ```bash
   cd frontend
   pnpm install
   pnpm build
   ```
   确认 `VITE_CDN` 为 false。把 `frontend/dist` 拷到车间，用 `nginx.conf.example` 反代 `/api`。
5. 启动后端三进程：
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\workshop\start.ps1
   ```
   或管理员执行 `install-nssm.ps1` 装成开机自启服务。

停止：`stop.ps1`（仅对 start.ps1 启动的进程生效）。

## Docker Hub 镜像（GitHub Actions）

推送标签 `V*` / `v*`（如 `V1.0.3`）或在 Actions 里手动 **Publish Docker Hub**，会构建并推送一体镜像：

- `{用户名}/limanalysis:V1.0.3`（及 `:latest`）
- 同一镜像角色：`app`（nginx+API）/ `api` / `collector` / `agg`

仓库 Secrets：

| Secret | 含义 |
| --- | --- |
| `DOCKERHUB` | Docker Hub **Access Token**（你已建的这个名字） |
| `DOCKERHUB_USER` | Docker Hub **用户名**（可选；不填则用 GitHub 仓库 owner，如 `poillysky`） |

确认 `DOCKERHUB` 里填的是 Token，不是用户名。Token：Docker Hub → Account Settings → Personal access tokens。

## NAS 应用单独部署（`/vol1/1000/Docker/limana`）

一体镜像 `limanalysis`：`app` + `collector` + `agg`；三库仍用 [`../docker-compose.nas.yml`](../docker-compose.nas.yml)。  
见 [`../limana/README.md`](../limana/README.md) 与 [`../docker-compose.limana.yml`](../docker-compose.limana.yml)。

## 桌面图标（PWA · Windows 独立窗口）

前端已支持安装为 **Windows 桌面应用样式**（无浏览器地址栏；Edge 支持标题栏控件叠加）。

1. `pnpm build` 后部署的站点需用 **HTTPS** 或 `http://localhost`（局域网纯 HTTP 时，Edge/Chrome 通常不允许安装 PWA）。
2. 车间机用 **Microsoft Edge** 打开系统 → 顶栏出现「安装到桌面」时点击；或地址栏右侧 ⊕ / 菜单「应用 → 安装此站点为应用」。
3. 安装后可在开始菜单找到 **LimAnalysis**，右键「固定到任务栏」或「发送到桌面」。
4. 打开后为独立窗口；支持拖拽顶栏移动窗口（`window-controls-overlay`）。

若必须走局域网 HTTP：在 Edge 中把该源加入「将不安全的源视为安全」（仅内网机），或给 nginx 配自签/内网证书。

## 车间离线模式

- `.env`：`WORKSHOP_OFFLINE=true`（强制），或 API `PUT /api/v1/system/workshop` `{"offline": true}`。
- 效果：不投递 SFC 定时采集；AI 测试/列表/启用 503；公式仍可用规则生成。
- 班前能连 SFC 的采集机：设 `WORKSHOP_OFFLINE=false` 并打开 SFC 爬虫 `is_active`。

## 值守检查

| 项 | 怎么看 |
| --- | --- |
| 进程 | 任务管理器 / NSSM 三服务 / `pids.json`；或看板页运行条 / `workers.*.alive` |
| 健康 | `GET http://127.0.0.1:8000/api/health` 或 `/api/v1/system/runtime-status`；前端「异常监控」页顶栏 |
| 三库 | health 里 `stores.raw/dwh/defect.ok` |
| Worker | `workers.collector/agg.alive`（心跳约 45s 内）；未起则整体 `degraded` |
| 调度 | `schedulers.*.last_run_*`；车间 offline 时 SFC 应 `blocked_by_workshop` |
| 磁盘 | 功能管理 → 磁盘清理；或 cleanup last_run |
| 前端图标 | 断公网侧栏仍有图标（本地 Iconify） |
| Metabase | 不可用时看板空态提示，交叉表/扫码不受影响 |

## 内存与流畅度（防膨胀）

| 风险 | 处理 |
| --- | --- |
| `meta_jobs` / 采集日志无限涨 | 磁盘清理 + Worker 启动时 prune（保留约 14 天 / 最多 800 条任务） |
| SQLAlchemy 连接池 | 每库 pool_size=3，三进程合计可控 |
| Metabase JVM 吃光 NAS | compose 里 `JAVA_OPTS -Xmx1024m` + `mem_limit: 1536m` |
| Postgres 默认缓存偏大 | `shared_buffers=128MB` + 容器 `mem_limit` |
| 首页每分钟重查交叉表 | 通知 60s，摘要 5 分钟 |

NAS 改完 compose 后需 `docker compose -f docker-compose.nas.yml up -d` 重建容器使内存参数生效。

## 备份清单

定期拷贝：

1. `data/meta/lim_meta.sqlite`（及 `-wal`/`-shm` 若存在，先停服务再拷最稳）
2. NAS 上 Postgres 数据卷（raw / dwh / defect）
3. 图片根目录（功能管理里配置的路径）
4. `backend/.env`（不含进 Git）

恢复：还原文件 → 起 Postgres → `start.ps1` / NSSM → 浏览器验证登录与首页。

## 离线验收（断公网）

- [ ] 登录成功  
- [ ] 首页通知播报 + 良率/扫码摘要有数  
- [ ] 自动外观数据分析 / 人工外观次品分析可用  
- [ ] 侧栏图标不空白  
- [ ] `/api/health` 返回 stores 状态  
- [ ] AI 页提示车间离线禁用  
- [ ] Metabase 停掉后看板友好提示，其它页正常  
- [ ] 杀一个 worker 后 NSSM 自动拉起（或脚本重启）

## 相关接口

- `GET /api/health` — 综合状态  
- `GET /api/v1/system/runtime-status` — 同上（鉴权前缀内）  
- `GET/PUT /api/v1/system/workshop` — 车间 offline 开关  
