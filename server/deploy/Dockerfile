# 阶段 1：网页端前端编译构建
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY frontend/ ./
RUN npm run build

# 阶段 2：Python 统一后端（同时服务网页端、Android 更新与微信小程序）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY server/requirements.txt ./
ARG PIP_INDEX_URL=""
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
RUN pip install --no-cache-dir -r requirements.txt

# 后端源码、管理后台静态页、迁移配置
COPY server/app ./app
COPY server/admin ./admin
COPY server/alembic.ini server/pyproject.toml ./
COPY server/migrations ./migrations

# 网页端构建产物（compose 场景改由 volume 挂载以便热更；此为无 volume 时的兜底）
COPY --from=frontend-builder /build/dist ./frontend/dist

EXPOSE 8000

# init_db 为幂等就地迁移，兼容全新库与两侧旧库；alembic 仅用于全新库的版本化基线
CMD ["sh", "-c", "(alembic upgrade head || true) && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
