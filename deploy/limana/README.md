# LimAnalysis 应用单独部署（`/vol1/1000/Docker/limana`）

只跑 **web + api + collector + agg**，不包含 Postgres / Adminer / Metabase。

| 组件 | Compose |
| --- | --- |
| 本项目应用 | [`../docker-compose.limana.yml`](../docker-compose.limana.yml) |
| 三库 + Adminer + Metabase（已有） | [`../docker-compose.nas.yml`](../docker-compose.nas.yml) → `/vol1/1000/Docker/LimAnalysis` |

镜像：`poillysky/limanalysis-frontend:V1.0.0`、`poillysky/limanalysis-backend:V1.0.0`

## 目录

```text
/vol1/1000/Docker/limana/
  .env
  nginx-web.conf
  meta/                 # lim_meta.sqlite
  raw/                  # CSV 落地
  photos/
    mold/
    appearance/
```

三库数据仍在 `/vol1/1000/Docker/LimAnalysis/{lim-raw,lim-dwh,lim-defect}`，由 `docker-compose.nas.yml` 维护。

## 启动

先保证 NAS 三库已起（`docker-compose.nas.yml`），再起应用：

```bash
ROOT=/vol1/1000/Docker/limana
mkdir -p "$ROOT"/{meta,raw,photos/mold,photos/appearance}
cp limana/.env.example "$ROOT/.env"
cp limana/nginx.conf "$ROOT/nginx-web.conf"
# 编辑 $ROOT/.env：CORS_ORIGINS；若 PG 连不上则改 PG_HOST 为 NAS IP

cd deploy   # 或仓库里的 deploy 目录
docker compose --env-file "$ROOT/.env" -f docker-compose.limana.yml pull
docker compose --env-file "$ROOT/.env" -f docker-compose.limana.yml up -d
```

## 端口

| 服务 | 端口 |
| --- | --- |
| 前端 | 8080 |
| API | 8000 |
| PG（已有栈） | 15432 / 15433 / 15434 |

## 图片路径

功能管理 → 图片目录：

- 注塑机：`/data/photos/mold`
- 自动外观：`/data/photos/appearance`
