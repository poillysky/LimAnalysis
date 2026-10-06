# 旧后端逻辑（对照用）

从 Docker 镜像还原后**只保留后端实现**。不做运行数据、不做前端、不做部署脚本。

| 目录 | 内容 |
|------|------|
| `sfc-crawler/` | SFC 登录下载、CSV 解析、MySQL UPSERT、调度与 API |
| `etl-app/` | ETL 模型、字段映射、SQL 生成与执行调度 |
| `lqins/` | 图片转移/归档、巡机配置与 API（`config.yaml` 含缺陷类型等运行配置） |

这些是过时实现，给 LIM Insight 对照职责，不要直接合并进新平台。
