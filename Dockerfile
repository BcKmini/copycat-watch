# Cloud Run 단일 컨테이너 이미지.
# nginx가 빌드된 프론트엔드 정적 파일을 서빙하고 /api 요청은 같은 컨테이너 안의
# uvicorn(127.0.0.1:8000)으로 프록시한다. => 서비스 1개 = URL 1개, scale-to-zero.
# (로컬 개발/쿠버네티스 배포는 기존 backend/Dockerfile, frontend/Dockerfile을 그대로 쓴다.)

# ---- 1) 프론트엔드 빌드 ----
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /fe/dist

# ---- 2) 백엔드 + nginx 런타임 ----
FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .

COPY --from=frontend /fe/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/start.sh /start.sh
RUN chmod +x /start.sh

# Cloud Run은 $PORT(기본 8080)로 헬스체크/트래픽을 보낸다. nginx가 이 포트를 듣는다.
EXPOSE 8080
CMD ["/start.sh"]
