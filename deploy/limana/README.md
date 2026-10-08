# LimAnalysis 应用单独部署（`/vol1/1000/Docker/limana`）

一体镜像：`poillysky/limanalysis:V1.0.0`（前端 + API + Worker）  
Compose：[`../docker-compose.limana.yml`](../docker-compose.limana.yml)  
三库仍用 [`../docker-compose.nas.yml`](../docker-compose.nas.yml)。

无需 `.env`。

## 目录

```text
/vol1/1000/Docker/limana/
  meta/     # lim_meta.sqlite
  raw/      # CSV 落地
  zsj/      # 注塑机图片（容器内 /data/photos/zsj）
  zdwg/     # 自动外观图片（容器内 /data/photos/zdwg）
```

## 启动

```bash
mkdir -p /vol1/1000/Docker/limana/{meta,raw,zsj,zdwg}
cd deploy
docker compose -f docker-compose.limana.yml pull
docker compose -f docker-compose.limana.yml up -d
```

访问：`http://<NAS>:8080`  
功能管理图片目录：注塑机 `/data/photos/zsj`，自动外观 `/data/photos/zdwg`。
