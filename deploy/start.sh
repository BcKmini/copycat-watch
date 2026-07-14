#!/bin/sh
# Cloud Run 단일 컨테이너 진입점: uvicorn(백엔드)을 백그라운드로 띄우고
# nginx(정적 서빙 + /api 프록시)를 포그라운드로 실행한다.
set -e

# 백엔드: 컨테이너 내부에서만 접근(127.0.0.1). scan 엔드포인트는 sync라
# FastAPI 워커 스레드풀에서 처리되므로 이벤트 루프를 막지 않는다.
uvicorn main:app --host 127.0.0.1 --port 8000 &

# cold start 직후 uvicorn이 소켓을 열기 전에 요청이 오면 502가 뜬다.
# 백엔드가 준비될 때까지(최대 30초) 기다린 뒤 nginx를 올린다.
python - <<'PY'
import time, urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1)
        break
    except Exception:
        time.sleep(0.5)
PY

# 프론트 + 프록시: Cloud Run이 헬스체크하는 8080 포트를 듣는다(daemon off로 포그라운드)
exec nginx -g 'daemon off;'
