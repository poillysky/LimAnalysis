# 工作区目录结构

仓库按「一层一个职责」划分。新功能尽量只在对应层新增文件。

```
LimAnalysis/
├── docs/                     # 需求、设计、决策（先文档后代码）
├── frontend/                 # 展示层：Vue3 + Pure Admin 精简版
├── backend/                  # Python 工程（FastAPI + 任务，同一解释器）
│   ├── app/                  # 应用服务层：HTTP API 与业务模块
│   │   ├── api/              # 路由汇总
│   │   ├── core/             # 配置、双库连接、统一响应
│   │   └── modules/          # anomaly / defect / faca …
│   ├── collector/            # 采集层：SFC CSV → ODS（只写生产库原始层）
│   ├── processor/            # 数据处理层：清洗、关联、指标
│   │   └── metrics/          # 一个文件一个指标
│   ├── db/sql/               # 生产库 / 元数据库 DDL（确认字段后再写）
│   ├── tests/
│   └── requirements.txt
├── data/meta/                # SQLite 项目元数据
├── data/raw/                 # 本机 CSV 落地，不入库 git
├── deploy/                   # docker compose、nginx
├── scripts/                  # 启动与补数脚本
└── README.md
```

## 层与库

| 目录 | 读 | 写 |
| --- | --- | --- |
| `backend/collector` | SQLite 项目配置 | `data/raw` 临时 CSV；成功后写 `lim_raw` 并删文件；摘要写 SQLite |
| `backend/processor` | `lim_raw` | `lim_dwh` DWD/ADS |
| `backend/app` | `lim_dwh` + SQLite | FACA、配置（不写 raw） |
| `frontend` | 只打 API | 无直连数据库 |

替换 SFC 网页为正式 API 时：只改 / 新增 `backend/collector`，其它目录契约不变。

## 加功能落点

1. 配置 → SQLite `meta_projects` / `meta_settings`（管理接口）  
2. 计算 → `backend/processor/` 或 `metrics/`  
3. 表 → `backend/db/sql/`  
4. 接口 → `backend/app/modules/<name>/`  
5. 页面 → `frontend/src/views/` + `router/modules/` + `api/modules/`
