"""Copycat Watch API 진입점. FastAPI 앱 초기화와 라우터만 담고, 실제 로직은
각 모듈(scanning / documents / demo ...)에 위임한다.
"""
import io
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

from core.config import DEMO_DIR, MAX_SCAN_IMAGES, MAX_UPLOAD_BYTES
from reports import documents
from reports.schemas import BatchReportRequest, LegalGuideRequest, ReportRequest
from scan import demo
from scan.demo import load_demo_hashes
from scan.scanning import Query, dedupe_matches, scan_demo, scan_web  # noqa: F401 (dedupe_matches: 테스트에서 참조)

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Copycat Watch API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    load_demo_hashes()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/demo-image/{fname}")
def demo_image(fname: str):
    # 매치로 반환된 파일명만 참조하므로 화이트리스트 검사로 경로 탈출을 막는다
    if fname not in demo.demo_hashes:
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return FileResponse(os.path.join(DEMO_DIR, fname))


@app.post("/api/scan")
def scan(file: list[UploadFile] = File(...)):
    # 주의: async def로 만들면 안 된다 - scan_web의 블로킹 작업(외부 이미지 수십 장 다운로드)이
    # 이벤트 루프를 통째로 막아 스캔 중 /health가 응답 못 한다. sync def는 FastAPI가 워커
    # 스레드에서 실행하므로 이벤트 루프가 계속 살아있다.
    #
    # 여러 장을 올리면 각 후보를 모든 업로드 이미지와 대조해 '가장 높은' 유사도를 취한다
    # → 같은 상품의 다른 각도/배경 사본까지 놓치지 않아 재현율이 오른다.
    images, contents = [], []
    for f in file[:MAX_SCAN_IMAGES]:
        content = f.file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "이미지 용량이 너무 커요 (최대 10MB)")
        try:
            img = Image.open(io.BytesIO(content))
            img.load()  # 잘린(truncated) 파일은 여기서 강제 디코딩해 미리 걸러낸다
            img = img.convert("RGB")
        except Exception:
            raise HTTPException(400, "이미지 파일을 읽을 수 없습니다")
        images.append(img)
        contents.append(content)

    if not images:
        raise HTTPException(400, "이미지가 필요합니다")

    query = Query(images)
    # 후보 발굴(Vision Web Detection)은 첫 이미지로 하고, 검증은 모든 이미지로 한다.
    web_result = scan_web(contents[0], query)
    if web_result is not None:
        return {"matches": web_result["matches"], "mode": "web",
                "label": web_result["label"], "images": len(images)}

    return {"matches": scan_demo(query), "mode": "demo", "label": None, "images": len(images)}


@app.post("/api/report")
def generate_report(req: ReportRequest):
    report, ai_generated = documents.build_report(req)
    return {"report": report, "ai_generated": ai_generated}


@app.post("/api/report/batch")
def generate_batch_report(req: BatchReportRequest):
    if not req.matches:
        raise HTTPException(400, "선택된 매치가 없습니다")
    report, ai_generated = documents.build_batch_report(req)
    return {"report": report, "ai_generated": ai_generated}


@app.post("/api/legal-guide")
def generate_legal_guide(req: LegalGuideRequest):
    report, ai_generated = documents.build_legal_guide(req)
    return {"report": report, "ai_generated": ai_generated}
