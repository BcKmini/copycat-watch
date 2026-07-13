import io
import os
import subprocess
from datetime import date

import imagehash
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel

load_dotenv()

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
SIMILARITY_THRESHOLD = 35  # 이 이상만 '도용 의심'으로 표시 (실사 기반 데모 데이터로 튜닝한 값)

FAKE_LISTINGS = {
    "soap01_copied_shopA.png": {"shop": "OO마켓 셀러 미소상회", "price": "8,900원", "note": "원가보다 30% 저렴하게 판매 중"},
    "soap01_copied_shopB.png": {"shop": "스마트스토어 데일리샵", "price": "9,500원", "note": "워터마크 붙여 재판매"},
    "candle01_copied_shopA.png": {"shop": "OO마켓 홈라이프", "price": "11,000원", "note": "상세페이지 사진 그대로 도용"},
    "candle01_copied_shopB.png": {"shop": "인스타 공동구매 계정", "price": "10,500원", "note": "SNS에서 재판매 중"},
    "tote01_copied_shopA.png": {"shop": "OO마켓 에코라이프", "price": "6,900원", "note": "제품명만 바꿔서 등록"},
    "tote01_copied_shopB.png": {"shop": "스마트스토어 그린데일리", "price": "7,200원", "note": "동일 사진 좌우반전 후 사용"},
}

app = FastAPI(title="Copycat Watch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_demo_hashes: dict[str, imagehash.ImageHash] = {}


def _load_demo_hashes():
    if not os.path.isdir(DEMO_DIR) or not os.listdir(DEMO_DIR):
        subprocess.run(["python", os.path.join(os.path.dirname(__file__), "gen_demo_data.py")], check=True)
    _demo_hashes.clear()
    for fname in os.listdir(DEMO_DIR):
        if fname.lower().endswith(".png"):
            path = os.path.join(DEMO_DIR, fname)
            _demo_hashes[fname] = imagehash.phash(Image.open(path))


@app.on_event("startup")
def startup():
    _load_demo_hashes()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    content = await file.read()
    try:
        query_img = Image.open(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "이미지 파일을 읽을 수 없습니다")

    query_hash = imagehash.phash(query_img)
    query_flip_hash = imagehash.phash(query_img.transpose(Image.FLIP_LEFT_RIGHT))

    matches = []
    for fname, h in _demo_hashes.items():
        if "original" in fname or "unrelated" in fname:
            continue
        # 좌우반전 도용까지 잡기 위해 원본/반전 해시 중 더 가까운 쪽을 사용
        distance = int(min(query_hash - h, query_flip_hash - h))
        similarity = round(max(0, 100 - distance * 3), 1)
        if similarity >= SIMILARITY_THRESHOLD:
            listing = FAKE_LISTINGS.get(fname, {"shop": "알 수 없는 판매처", "price": "-", "note": ""})
            matches.append({
                "file": fname,
                "similarity": similarity,
                "shop": listing["shop"],
                "price": listing["price"],
                "note": listing["note"],
            })

    matches.sort(key=lambda m: -m["similarity"])
    return {"matches": matches}


class ReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    match_shop: str
    match_note: str
    similarity: float


REPORT_SYSTEM_PROMPT = """너는 소상공인의 지식재산권 침해 신고를 돕는 어시스턴트야.
입력된 상품 도용 정황을 바탕으로 아래 두 문서를 한국어로 작성해.

1. [플랫폼 신고 사유서] - 오픈마켓/SNS 플랫폼에 이미지 도용을 신고할 때 제출할 사유서 (300자 내외, 사실관계+요청사항)
2. [내용증명 초안] - 도용 판매자에게 보낼 내용증명 초안 (발신인/수신인 자리는 [ ]로 표시, 정중하지만 단호한 어조, 판매중지 및 손해배상 요구 포함)

각 문서는 "---문서1---", "---문서2---" 구분자로 나눠서 출력해. 서론 없이 바로 문서 내용만 출력해."""


@app.post("/api/report")
def generate_report(req: ReportRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    user_prompt = (
        f"상품명: {req.product_name}\n"
        f"신고인(원 판매자): {req.seller_name}\n"
        f"도용 발견 판매처: {req.match_shop}\n"
        f"정황: {req.match_note}\n"
        f"이미지 유사도: {req.similarity}%\n"
        f"오늘 날짜: {date.today().isoformat()}"
    )

    if not api_key:
        return {
            "report": (
                "---문서1---\n"
                f"[플랫폼 신고 사유서 - 임시 템플릿]\n"
                f"본인이 판매 중인 '{req.product_name}' 상품 이미지가 '{req.match_shop}'에서 "
                f"무단으로 사용되고 있음을 확인했습니다({req.match_note}). "
                f"이미지 유사도 분석 결과 {req.similarity}% 일치하여 명백한 도용으로 판단되며, "
                "해당 게시물의 판매 중지 및 이미지 삭제 조치를 요청합니다.\n\n"
                "---문서2---\n"
                "[내용증명 초안 - 임시 템플릿]\n"
                "발신인: [본인 성명/상호]\n수신인: [상대방 상호/성명]\n\n"
                f"귀하가 판매 중인 상품의 이미지가 본인이 판매 중인 '{req.product_name}' 상품 사진과 "
                f"동일하거나 매우 유사함을 확인하였습니다. 이는 저작권 침해에 해당하며, "
                "본 통지 수령 후 7일 이내 해당 상품의 판매를 중단하고 이미지를 삭제할 것을 요청합니다. "
                "미이행 시 법적 조치를 진행할 수 있음을 알려드립니다.\n\n"
                "[ANTHROPIC_API_KEY 미설정 - console.anthropic.com에서 키 발급 후 .env에 추가하면 AI가 상황별로 맞춤 작성합니다]"
            )
        }

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return {"report": resp.content[0].text}
