# Google Cloud Run 배포 가이드

카피캣 워치를 Google Cloud Run에 올려 **URL 하나로 상시 구동**하는 방법이다.
프론트엔드(nginx 정적 서빙)와 백엔드(FastAPI)를 **단일 컨테이너**로 묶어 서비스
1개로 배포한다. 요청이 없을 땐 인스턴스가 0으로 줄어(scale-to-zero) 비용이 거의
들지 않고, 요청이 오면 자동으로 뜬다.

관련 파일:
- [`Dockerfile`](Dockerfile) — Cloud Run용 단일 컨테이너 이미지(프론트 빌드 + 백엔드 + nginx)
- [`deploy/nginx.conf`](deploy/nginx.conf) — 정적 서빙 + `/api` 프록시(127.0.0.1:8000)
- [`deploy/start.sh`](deploy/start.sh) — uvicorn 백그라운드 + 백엔드 준비 대기 + nginx 포그라운드

> 로컬 개발/쿠버네티스 배포는 기존 `docker-compose.yml`, `k8s/`, `backend/Dockerfile`,
> `frontend/Dockerfile`을 그대로 쓴다. 위 파일들은 Cloud Run 전용이다.

---

## 1. 사전 준비

### 1-1. gcloud CLI 설치 & 로그인
```bash
# 설치되어 있지 않다면: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>
```

### 1-2. 결제 계정 연결
Cloud Run·Cloud Build·Secret Manager는 결제 계정이 연결된 프로젝트에서만 동작한다
(무료 등급 안이면 실제 청구는 거의 0). 콘솔 > 결제에서 프로젝트에 결제 계정을 연결한다.

### 1-3. 필요한 API 활성화
```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  vision.googleapis.com
```

---

## 2. API 키를 Secret Manager에 저장

키를 코드나 환경변수에 하드코딩하지 않고 Secret Manager에 넣은 뒤 Cloud Run이
런타임에 주입하도록 한다.

```bash
# Anthropic API 키 (신고서·법적 가이드 AI 생성용)
printf '%s' "sk-ant-..." | gcloud secrets create anthropic-api-key --data-file=-

# Google Vision API 키 (웹 이미지 검색용)
printf '%s' "AIza..." | gcloud secrets create google-vision-api-key --data-file=-
```

> 키가 없어도 앱은 데모 폴백 모드로 동작한다(내장 데모 데이터셋으로 매칭, 신고서는
> 템플릿 기반). 두 키를 생략하면 아래 배포 명령에서 `--set-secrets` 부분만 빼면 된다.

### Cloud Run 런타임 서비스 계정에 시크릿 접근 권한 부여
```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in anthropic-api-key google-vision-api-key; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

---

## 3. 배포

레포 루트에서 한 줄이면 된다. `--source .`가 루트의 `Dockerfile`을 Cloud Build로
빌드해 Artifact Registry에 올리고 Cloud Run에 배포까지 한다.

```bash
gcloud run deploy copycat-watch \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --concurrency 20 \
  --min-instances 0 \
  --max-instances 3 \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,GOOGLE_VISION_API_KEY=google-vision-api-key:latest"
```

- `--region asia-northeast3` : 서울 리전(한국 사용자 지연시간 최소)
- `--allow-unauthenticated` : 공개 웹앱이므로 누구나 접근 허용
- `--memory 1Gi` : 이미지 여러 장 동시 해싱 시 OOM 방지(k8s에서 검증한 값과 동일)
- `--timeout 300` : 스캔이 오래 걸릴 수 있어 요청 타임아웃 5분
- `--min-instances 0` : 요청 없으면 0으로 축소(비용 절감). 콜드스타트가 싫으면 `1`
- `--max-instances 3` : 폭주 시 상한(비용 폭발 방지)

배포가 끝나면 `https://copycat-watch-xxxxx-du.a.run.app` 형태의 URL이 출력된다.
이게 상시 구동되는 공개 주소다.

---

## 4. 비용 감각

| 항목 | 과금 방식 | 비고 |
|---|---|---|
| Cloud Run | 요청 처리 중 vCPU·메모리 사용 시간만 과금 | 무료 등급: 월 200만 요청 / 360k GB-초 / 180k vCPU-초. 데모/공모전 수준 트래픽은 사실상 무료 |
| min-instances=1(상시 예열) | 인스턴스 1개를 항상 유지 | 콜드스타트 제거 대신 월 몇 달러 발생 |
| Cloud Build | 빌드 분당 과금 | 무료 등급 월 120분. 재배포 몇 번은 무료 |
| Anthropic API | 신고서·법적 가이드 생성 1건당 토큰 과금 | 사용자가 실제로 문서를 생성할 때만 발생 |
| Google Vision | 이미지 1건당 | 무료 1,000건/월, 이후 1,000건당 약 $1.50 |

정리: **호스팅 자체는 무료 등급 안에서 거의 0**이고, 실제 비용은 사용자가 AI 기능
(신고서 생성·웹 검색)을 얼마나 쓰느냐에 비례한다.

---

## 5. 재배포

코드를 바꾼 뒤 같은 명령을 다시 실행하면 새 리비전으로 무중단 롤아웃된다.
```bash
gcloud run deploy copycat-watch --source . --region asia-northeast3
```
(2회차부터는 이미 설정된 시크릿·리소스 값이 유지되므로 플래그를 줄여도 된다.)

---

## 6. (선택) 배포 전 로컬에서 동일 이미지 검증

Cloud Run에 올리기 전에, Cloud Run과 동일한 컨테이너를 로컬에서 그대로 띄워볼 수 있다.
```bash
docker build -t copycat-cloudrun:test -f Dockerfile .
docker run --rm -p 8090:8080 \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e GOOGLE_VISION_API_KEY="AIza..." \
  copycat-cloudrun:test
# http://localhost:8090 접속 (키 없이 실행하면 데모 폴백 모드)
```

---

## 7. (선택) 커스텀 도메인

```bash
gcloud run domain-mappings create \
  --service copycat-watch \
  --domain your-domain.com \
  --region asia-northeast3
```
출력되는 DNS 레코드를 도메인 등록업체에 추가하면 HTTPS 인증서까지 자동 발급된다.

---

## 8. (선택) GitHub 푸시 시 자동 배포

Cloud Run 콘솔 > 서비스 > "Set up continuous deployment"에서 GitHub 레포를 연결하면,
지정한 브랜치에 푸시할 때마다 Cloud Build가 `Dockerfile`로 빌드해 자동 배포한다.
별도 워크플로우 파일 없이 콘솔 UI만으로 설정된다.
