# LimAnalysis 一体镜像：前端静态 + API + Worker
#   docker run … limanalysis app          # nginx(:80) + uvicorn
#   docker run … limanalysis api
#   docker run … limanalysis collector
#   docker run … limanalysis agg

FROM node:20-alpine AS frontend-build

WORKDIR /fe
RUN corepack enable \
  && corepack prepare pnpm@9 --activate

ARG NPM_REGISTRY=https://registry.npmjs.org
RUN npm config set registry "${NPM_REGISTRY}"

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        nginx \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /fe/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS "http://127.0.0.1/api/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["app"]
