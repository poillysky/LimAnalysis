# LimAnalysis 应用单独部署（`/vol1/1000/Docker/limana`）

一体镜像：`poillysky/limanalysis:V1.0.6`（前端 + API + Worker）  
Compose：[`../docker-compose.limana.yml`](../docker-compose.limana.yml)  
三库仍用 [`../docker-compose.nas.yml`](../docker-compose.nas.yml)。

无需 `.env`。

## 目录

```text
/vol1/1000/Docker/limana/
  meta/        # lim_meta.sqlite（字段配置）
  raw/         # CSV 落地
  sql_models/  # ETL/聚合生成的 .sql（layer1 / layer2）
  zsj/         # 注塑机图片（容器内 /data/photos/zsj）
  zdwg/        # 自动外观图片（容器内 /data/photos/zdwg）
```

## 启动

```bash
mkdir -p /vol1/1000/Docker/limana/{meta,raw,sql_models,zsj,zdwg}
cd deploy
docker compose -f docker-compose.limana.yml pull
docker compose -f docker-compose.limana.yml up -d
```

保存清洗/聚合配置后，SQL 文件写在 `sql_models/` 卷上，换镜像也不会丢。若旧库里还是绝对路径，跑一次「保存并生成 SQL」或触发清洗即可自动重生并改成相对路径。

访问：`http://<NAS>:18088`  
功能管理图片目录：注塑机 `/data/photos/zsj`，自动外观 `/data/photos/zdwg`。
