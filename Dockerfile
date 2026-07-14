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

# ---- 2) 백엔드 + nginx + 로컬 LLM 런타임 ----
FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements-llm.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# llama-cpp-python: abetlen 프리빌트 CPU 휠(linux_x86_64 태그)은 musl 링크라 Debian(glibc)에서
# libllama.so 로드에 실패한다. PyPI sdist를 glibc로 직접 컴파일하고, 빌드 도구는 같은 레이어에서
# 제거해 이미지 비대화를 막는다(런타임엔 libgomp1·libstdc++6만 필요).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && pip install --no-cache-dir -r requirements-llm.txt \
    && apt-get purge -y --auto-remove build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# 오픈소스 신고서 생성 모델(Qwen2.5-1.5B-Instruct Q4_K_M, Apache-2.0)을 이미지에 내장.
# 신고서 요청 때만 지연 로딩되므로 스캔 경로의 콜드스타트에는 영향이 없다.
ENV LOCAL_LLM_PATH=/models/model.gguf
# HF는 익명 curl(기본 User-Agent)·데이터센터 IP의 LFS 다운로드를 403으로 막을 때가 있어
# 브라우저 User-Agent와 재시도를 명시한다(Cloud Build에서 확인된 403 회피).
RUN mkdir -p /models \
    && curl -fSL --retry 5 --retry-delay 5 --retry-all-errors \
       -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36" \
       -o /models/model.gguf \
       "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true"

COPY backend/ .

COPY --from=frontend /fe/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/start.sh /start.sh
# Windows 체크아웃(CRLF)이어도 셔뱅이 깨지지 않도록 CR 제거 후 실행권한 부여
RUN sed -i 's/\r$//' /start.sh && chmod +x /start.sh

# Cloud Run은 $PORT(기본 8080)로 헬스체크/트래픽을 보낸다. nginx가 이 포트를 듣는다.
EXPOSE 8080
CMD ["/start.sh"]
