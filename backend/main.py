import base64
import io
import json
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import imagehash
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from matching import SIMILARITY_THRESHOLD, candidate_hashes, query_hashes, similarity_from_hashes

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("copycat-watch")

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
ASSUMED_MONTHLY_SALES = 20  # 예상 피해액 계산용 가정치 (데모 - 실제 서비스에선 플랫폼 판매지수 연동 필요)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


def _parse_price(price_str: str) -> int:
    digits = re.sub(r"[^0-9]", "", price_str)
    return int(digits) if digits else 0


def _estimate_damage(price_str: str) -> int:
    return _parse_price(price_str) * ASSUMED_MONTHLY_SALES

_listings: dict[str, dict] = {}

app = FastAPI(title="Copycat Watch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_demo_hashes: dict[str, tuple[imagehash.ImageHash, imagehash.ImageHash]] = {}


def _load_demo_hashes():
    if not os.path.isdir(DEMO_DIR) or not os.listdir(DEMO_DIR):
        subprocess.run(["python", os.path.join(os.path.dirname(__file__), "gen_demo_data.py")], check=True)
    _demo_hashes.clear()
    for fname in os.listdir(DEMO_DIR):
        if fname.lower().endswith(".png"):
            path = os.path.join(DEMO_DIR, fname)
            _demo_hashes[fname] = candidate_hashes(Image.open(path).convert("RGB"))

    _listings.clear()
    metadata_path = os.path.join(DEMO_DIR, "metadata.json")
    if os.path.isfile(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            _listings.update(json.load(f))


@app.on_event("startup")
def startup():
    _load_demo_hashes()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/demo-image/{fname}")
def demo_image(fname: str):
    # 매치로 반환된 파일명만 참조하므로 화이트리스트 검사로 경로 탈출을 막는다
    if fname not in _demo_hashes:
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return FileResponse(os.path.join(DEMO_DIR, fname))


FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CopycatWatch/1.0"}
VERIFY_TIMEOUT = 6  # 후보 이미지 1장 다운로드 제한시간(초)
VERIFY_MAX_BYTES = 5 * 1024 * 1024  # 후보 이미지 최대 크기
VERIFY_WORKERS = 8
WEB_RESULT_LIMIT = 15


def _verify_candidate_image(query_h, url: str) -> float | None:
    """후보 이미지를 직접 내려받아 프로덕션 유사도 알고리즘으로 실측 점수를 계산한다.
    다운로드/디코딩에 실패하면 None (검증 불가)."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=VERIFY_TIMEOUT, stream=True)
        resp.raise_for_status()
        data = resp.raw.read(VERIFY_MAX_BYTES + 1, decode_content=True)
        if len(data) > VERIFY_MAX_BYTES:
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        chash, ccolor = candidate_hashes(img.convert("RGB"))
        return similarity_from_hashes(query_h[0], query_h[1], query_h[2], chash, ccolor)
    except Exception:
        return None


def _scan_web(content: bytes, query_img: Image.Image) -> dict | None:
    """2단계 검색 파이프라인:
    1) Google Vision Web Detection으로 인터넷 전체에서 후보 페이지/이미지를 수집 (재현율 확보)
    2) 각 후보 이미지를 서버가 직접 내려받아 프로덕션 유사도 알고리즘(phash+colorhash)으로
       실측 검증·재정렬 (정밀도 확보)
    Vision의 '비슷해 보이는' 후보를 그대로 믿으면 무관한 상품이 상위에 섞이기 때문에,
    실측 유사도가 임계값 미만인 후보는 걸러낸다. 키가 없거나 API 실패 시 None(데모 폴백)."""
    api_key = os.environ.get("GOOGLE_VISION_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.post(
            f"https://vision.googleapis.com/v1/images:annotate?key={api_key}",
            json={
                "requests": [{
                    "image": {"content": base64.b64encode(content).decode()},
                    "features": [{"type": "WEB_DETECTION", "maxResults": 30}],
                }]
            },
            timeout=15,
        )
        resp.raise_for_status()
        web = resp.json()["responses"][0].get("webDetection", {})
    except Exception as e:
        logger.warning("Vision API 호출 실패, 데모 매칭으로 폴백: %s", e)
        return None

    # 1단계: 후보 수집. Vision이 그 페이지에서 실제로 매칭 이미지를 찾아준 경우만
    # 후보로 삼는다 - 이미지 근거 없이 "관련 있어 보이는 페이지"만 있는 건
    # 신뢰도가 너무 낮아서(제목만 비슷한 무관한 페이지가 섞임) 아예 제외한다.
    candidates = []
    seen_urls = set()
    for page in web.get("pagesWithMatchingImages", []):
        page_url = page.get("url")
        if not page_url or page_url in seen_urls:
            continue
        page_full = page.get("fullMatchingImages", [])
        page_partial = page.get("partialMatchingImages", [])
        if not page_full and not page_partial:
            continue  # 이미지 근거 없는 페이지는 노이즈이므로 제외
        seen_urls.add(page_url)
        thumb = (page_full or page_partial)[0].get("url")
        candidates.append({
            "key": page_url,
            "title": page.get("pageTitle") or page_url,
            "image_url": thumb,
            "source_url": page_url,
            "tier": "full" if page_full else "partial",
        })
    for img in web.get("visuallySimilarImages", [])[:8]:
        img_url = img.get("url")
        if not img_url or img_url in seen_urls:
            continue
        seen_urls.add(img_url)
        candidates.append({
            "key": img_url,
            "title": "게시 페이지 미확인",
            "image_url": img_url,
            "source_url": None,
            "tier": "similar",
        })

    # 2단계: 후보 이미지를 병렬로 내려받아 실측 유사도 검증
    query_h = query_hashes(query_img)
    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        verified = list(pool.map(
            lambda c: _verify_candidate_image(query_h, c["image_url"]), candidates
        ))

    # 검증 불가(이미지 다운로드 차단 등) 시 Vision 등급 기반 보수적 점수로 폴백
    TIER_FALLBACK = {"full": 85.0, "partial": 60.0, "similar": 0.0}
    TIER_NOTE = {
        "full": "웹에서 동일 이미지가 게시된 페이지",
        "partial": "웹에서 변형(크롭 등)된 이미지가 게시된 페이지",
        "similar": "게시 페이지를 특정하지 못한 유사 이미지",
    }

    matches = []
    for cand, measured in zip(candidates, verified):
        if measured is not None:
            similarity = measured
            note = f"{TIER_NOTE[cand['tier']]} · 원본 대비 실측 유사도 {measured}%"
        else:
            similarity = TIER_FALLBACK[cand["tier"]]
            note = f"{TIER_NOTE[cand['tier']]} · 이미지 직접 검증 불가(사이트 차단)"
        if similarity < SIMILARITY_THRESHOLD:
            continue
        matches.append({
            "file": cand["key"],
            "similarity": similarity,
            "shop": cand["title"],
            "price": "-",
            "note": note,
            "image_url": cand["image_url"],
            "estimated_damage": None,
            "source_url": cand["source_url"],
            "source": "web",
            "verified": measured is not None,
        })

    # 실측 검증된 결과를 우선하고, 같은 그룹 안에서는 유사도 내림차순
    matches.sort(key=lambda m: (-m["verified"], -m["similarity"]))
    matches = matches[:WEB_RESULT_LIMIT]

    best_guess = web.get("bestGuessLabels", [])
    label = best_guess[0]["label"] if best_guess else None
    return {"matches": matches, "label": label}


def _scan_demo(query_img: Image.Image) -> list[dict]:
    query_hash, query_flip_hash, query_color_hash = query_hashes(query_img)

    matches = []
    for fname, (cand_hash, cand_color_hash) in _demo_hashes.items():
        if "original" in fname or "unrelated" in fname:
            continue
        similarity = similarity_from_hashes(
            query_hash, query_flip_hash, query_color_hash, cand_hash, cand_color_hash
        )
        if similarity >= SIMILARITY_THRESHOLD:
            listing = _listings.get(fname, {"shop": "알 수 없는 판매처", "price": "-", "note": ""})
            matches.append({
                "file": fname,
                "similarity": similarity,
                "shop": listing["shop"],
                "price": listing["price"],
                "note": listing["note"],
                "image_url": f"/api/demo-image/{fname}",
                "estimated_damage": _estimate_damage(listing["price"]),
                "source_url": None,
                "source": "demo",
            })

    matches.sort(key=lambda m: -m["similarity"])
    return matches


@app.post("/api/scan")
async def scan(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "이미지 용량이 너무 커요 (최대 10MB)")
    try:
        query_img = Image.open(io.BytesIO(content))
        query_img.load()  # PIL은 open()에서 헤더만 읽고 실제 픽셀 디코딩은 미루기 때문에,
        # 잘린(truncated) 파일은 여기서 강제로 디코딩해서 미리 걸러낸다
        query_img = query_img.convert("RGB")
    except Exception:
        raise HTTPException(400, "이미지 파일을 읽을 수 없습니다")

    web_result = _scan_web(content, query_img)
    if web_result is not None:
        return {"matches": web_result["matches"], "mode": "web", "label": web_result["label"]}

    return {"matches": _scan_demo(query_img), "mode": "demo", "label": None}


class ReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    match_shop: str
    match_note: str
    similarity: float
    platform: str = "오픈마켓 일반"
    source_url: str | None = None
    estimated_damage: int | None = None


REPORT_SYSTEM_PROMPT = """너는 소상공인의 지식재산권 침해 신고를 돕는 어시스턴트야.
입력된 상품 도용 정황을 바탕으로 아래 세 문서를 한국어로 작성해.

1. [플랫폼 신고 사유서] - 지정된 플랫폼에 이미지 도용을 신고할 때 제출할 사유서 (300자 내외, 사실관계+요청사항). 플랫폼별로 신고 절차/용어가 다르니 해당 플랫폼에 맞게 조정해.
2. [내용증명 초안] - 도용 판매자에게 보낼 내용증명 초안 (발신인/수신인 자리는 [ ]로 표시, 정중하지만 단호한 어조, 판매중지 및 손해배상 요구 포함)
3. [손해배상 청구 내역서] - 예상 피해액이 주어졌다면 그 금액과 산정 근거(판매가 x 예상 판매량)를 명시한 간단한 청구 내역. 예상 피해액이 없다면 "정확한 피해 산정을 위해 상대방 판매 이력 확인이 필요하다"는 취지로 작성해.

각 문서는 "---문서1---", "---문서2---", "---문서3---" 구분자로 나눠서 출력해. 서론 없이 바로 문서 내용만 출력해."""


@app.post("/api/report")
def generate_report(req: ReportRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    damage_line = f"예상 피해액: {req.estimated_damage:,}원 (판매가 x 월 예상판매량 {ASSUMED_MONTHLY_SALES}개 가정)\n" if req.estimated_damage else ""
    source_line = f"발견된 게시물 URL: {req.source_url}\n" if req.source_url else ""
    user_prompt = (
        f"상품명: {req.product_name}\n"
        f"신고인(원 판매자): {req.seller_name}\n"
        f"신고 대상 플랫폼: {req.platform}\n"
        f"도용 발견 판매처: {req.match_shop}\n"
        f"정황: {req.match_note}\n"
        f"이미지 유사도: {req.similarity}%\n"
        f"{source_line}"
        f"{damage_line}"
        f"오늘 날짜: {date.today().isoformat()}"
    )

    if not api_key:
        damage_doc = (
            f"예상 피해액: {req.estimated_damage:,}원\n산정 근거: 판매가 x 월 예상판매량 {ASSUMED_MONTHLY_SALES}개(데모 가정치)"
            if req.estimated_damage
            else "정확한 피해액 산정을 위해서는 상대방의 실제 판매 이력 확인이 필요합니다. 플랫폼 고객센터에 판매량 정보 제공을 요청하세요."
        )
        return {
            "report": (
                "---문서1---\n"
                f"[{req.platform} 신고 사유서 - 임시 템플릿]\n"
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
                "---문서3---\n"
                f"[손해배상 청구 내역서 - 임시 템플릿]\n{damage_doc}\n\n"
                "[ANTHROPIC_API_KEY 미설정 - console.anthropic.com에서 키 발급 후 .env에 추가하면 AI가 상황별로 맞춤 작성합니다]"
            )
        }

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1536,
        system=REPORT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return {"report": resp.content[0].text}
