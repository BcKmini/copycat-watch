"""서비스 전역 상수. 여러 모듈이 공유하는 설정값을 한곳에 모은다."""
import os

# 백엔드 루트(이 파일은 backend/core/ 안에 있으므로 두 단계 위). 데모셋·스크립트 경로 기준.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 데모 데이터셋 경로. Vision 키가 없을 때 폴백 매칭에 쓴다.
DEMO_DIR = os.path.join(BACKEND_ROOT, "demo_data")

# 업로드 / 스캔 제한
MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 파일당 10MB
MAX_SCAN_IMAGES = 5                    # 다중 업로드 상한(같은 상품의 여러 각도)

# 예상 피해액 계산용 가정치(데모 - 실제 서비스에선 플랫폼 판매지수 연동 필요)
ASSUMED_MONTHLY_SALES = 20

# 후보 이미지 실측 다운로드 설정
FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CopycatWatch/1.0"}
VERIFY_TIMEOUT = 5                     # 후보 이미지 1장 다운로드 제한시간(초)
VERIFY_MAX_BYTES = 5 * 1024 * 1024     # 후보 이미지 최대 크기
VERIFY_WORKERS = 12                    # 동시 디코딩 메모리 피크 제한(OOM 방지)
WEB_RESULT_LIMIT = 50                  # 웹 스캔 결과 상한

# 게시 페이지 딥 검증 설정
PAGE_TIMEOUT = 8                       # 페이지 HTML 다운로드 제한시간(초)
PAGE_MAX_BYTES = 2 * 1024 * 1024       # 페이지 HTML 최대 크기
PAGE_MAX_IMAGES = 4                    # 페이지 안에서 대조해볼 이미지 최대 개수
