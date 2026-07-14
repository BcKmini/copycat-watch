import base64
import io
import json
import logging
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import imagehash
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from llm import refine_document
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


_KOR_DIGITS = "영일이삼사오육칠팔구"
_KOR_SMALL_UNITS = ["", "십", "백", "천"]
_KOR_BIG_UNITS = ["", "만", "억", "조"]


def _number_to_korean(n: int) -> str:
    """내용증명·손해배상 문서는 금액을 숫자와 한글로 병기하는 관행이 있어
    (예: 123,000원(금 일십이만삼천원)) 정식 한글 금액 표기를 생성한다."""
    if n == 0:
        return "영"
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        digits = [int(d) for d in str(g).zfill(4)]
        s = "".join(
            _KOR_DIGITS[d] + _KOR_SMALL_UNITS[3 - j]
            for j, d in enumerate(digits)
            if d != 0
        )
        parts.append(s + _KOR_BIG_UNITS[i])
    return "".join(parts)


def _format_amount(n: int) -> str:
    return f"{n:,}원(금 {_number_to_korean(n)}원)"

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
VERIFY_TIMEOUT = 5  # 후보 이미지 1장 다운로드 제한시간(초)
VERIFY_MAX_BYTES = 5 * 1024 * 1024  # 후보 이미지 최대 크기
VERIFY_WORKERS = 12  # 동시 디코딩 메모리 피크 제한 (OOM 방지)
WEB_RESULT_LIMIT = 50
PAGE_TIMEOUT = 8  # 페이지 HTML 다운로드 제한시간(초)
PAGE_MAX_BYTES = 2 * 1024 * 1024  # 페이지 HTML 최대 크기
PAGE_MAX_IMAGES = 4  # 페이지 안에서 대조해볼 이미지 최대 개수

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)
_IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


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
        if img.width * img.height > 25_000_000:
            return None  # 25MP 초과 초대형 이미지는 디코딩 자체가 메모리 폭탄이라 스킵
        # 해시는 어차피 32x32로 축소해 계산하므로 저해상도 디코딩해도 결과가 같다.
        # draft는 JPEG를 디코딩 단계에서 축소해 메모리 사용을 수십 배 줄인다 (OOM 방지).
        img.draft("RGB", (512, 512))
        img.load()
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        chash, ccolor = candidate_hashes(img)
        return similarity_from_hashes(query_h[0], query_h[1], query_h[2], chash, ccolor)
    except Exception:
        return None


def _extract_page_image_urls(page_url: str) -> list[str]:
    """페이지 HTML을 직접 방문해 og:image와 본문 <img> 이미지 URL들을 추출한다."""
    resp = requests.get(page_url, headers=FETCH_HEADERS, timeout=PAGE_TIMEOUT, stream=True)
    resp.raise_for_status()
    if "text/html" not in resp.headers.get("content-type", ""):
        return []
    html = resp.raw.read(PAGE_MAX_BYTES, decode_content=True).decode(
        resp.encoding or "utf-8", errors="ignore"
    )
    raw_urls = []
    for a, b in _OG_IMAGE_RE.findall(html):
        raw_urls.append(a or b)
    raw_urls.extend(_IMG_TAG_RE.findall(html))

    out, seen = [], set()
    for u in raw_urls:
        full = urljoin(page_url, u.strip())
        if full.startswith(("http://", "https://")) and full not in seen:
            seen.add(full)
            out.append(full)
        if len(out) >= PAGE_MAX_IMAGES:
            break
    return out


def _verify_candidate(query_h, cand: dict) -> tuple[float | None, str | None]:
    """후보를 실측 검증한다. 1) 후보 이미지 직접 대조 → 2) 실패 시 게시 페이지를
    직접 방문해서 페이지 안의 이미지들(og:image, 본문 img)을 하나씩 대조.
    반환: (실측 유사도 or None, 검증 방식 'image'/'page'/None)"""
    if cand.get("image_url"):
        sim = _verify_candidate_image(query_h, cand["image_url"])
        if sim is not None:
            return sim, "image"

    if cand.get("source_url"):
        try:
            page_image_urls = _extract_page_image_urls(cand["source_url"])
        except Exception:
            return None, None
        best = None
        for img_url in page_image_urls:
            sim = _verify_candidate_image(query_h, img_url)
            if sim is not None and (best is None or sim > best):
                best = sim
                if sim >= 90:  # 확실한 매치면 더 볼 필요 없음
                    break
        if best is not None:
            return best, "page"

    return None, None


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlparse(url.lower())
    netloc = p.netloc.removeprefix("www.")
    path = p.path.rstrip("/")
    return f"{netloc}{path}"  # 스킴/쿼리스트링/트레일링 슬래시 차이는 같은 페이지로 취급


def _dedupe_matches(matches: list[dict]) -> list[dict]:
    """같은 사이트의 같은 글이 http/https, www 유무, 쿼리스트링 차이 등으로
    여러 후보로 잡히거나, 같은 도메인+같은 제목+같은 유사도로 중복 표시되는
    경우 1건만 남긴다 (검증 성공한 쪽을 우선)."""
    best_by_key: dict[str, dict] = {}
    for m in matches:
        norm_url = _normalize_url(m["source_url"]) or _normalize_url(m["file"])
        domain = urlparse(m["source_url"] or m["file"]).netloc.lower().removeprefix("www.")
        key = norm_url or f"{domain}|{m['shop'].strip().lower()}|{m['similarity']}"
        existing = best_by_key.get(key)
        if existing is None or (m["verified"] and not existing["verified"]) or m["similarity"] > existing["similarity"]:
            best_by_key[key] = m
    return list(best_by_key.values())


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
                    "features": [{"type": "WEB_DETECTION", "maxResults": 100}],
                }]
            },
            timeout=15,
        )
        resp.raise_for_status()
        web = resp.json()["responses"][0].get("webDetection", {})
    except Exception as e:
        logger.warning("Vision API 호출 실패, 데모 매칭으로 폴백: %s", e)
        return None

    # 1단계: Vision이 주는 모든 단서를 빠짐없이 후보로 수집한다.
    # - 매칭 이미지가 있는 페이지 (full/partial)
    # - 이미지 근거가 없는 페이지도 포함: 뒤에서 페이지를 직접 방문해 검증한다
    # - 페이지를 특정 못한 최상위 동일/부분일치 이미지
    # - 시각적으로 유사한 이미지 전부 (개수 제한 없음)
    candidates = []
    seen_urls = set()

    def _add(key, title, image_url, source_url, tier):
        if not key or key in seen_urls:
            return
        seen_urls.add(key)
        candidates.append({
            "key": key, "title": title, "image_url": image_url,
            "source_url": source_url, "tier": tier,
        })

    for page in web.get("pagesWithMatchingImages", []):
        page_url = page.get("url")
        page_full = page.get("fullMatchingImages", [])
        page_partial = page.get("partialMatchingImages", [])
        thumb = (page_full or page_partial or [{}])[0].get("url")
        tier = "full" if page_full else ("partial" if page_partial else "page")
        _add(page_url, page.get("pageTitle") or page_url, thumb, page_url, tier)

    for img in web.get("fullMatchingImages", []):
        _add(img.get("url"), "게시 페이지 미확인 (동일 이미지)", img.get("url"), None, "full_image")
    for img in web.get("partialMatchingImages", []):
        _add(img.get("url"), "게시 페이지 미확인 (부분 일치)", img.get("url"), None, "partial_image")
    for img in web.get("visuallySimilarImages", []):
        _add(img.get("url"), "게시 페이지 미확인", img.get("url"), None, "similar")

    # 2단계: 전 후보를 병렬 실측 검증. 이미지 직접 대조가 막히면 게시 페이지를
    # 직접 방문(딥 검증)해서 페이지 안 이미지들과 대조한다.
    query_h = query_hashes(query_img)
    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        verified = list(pool.map(lambda c: _verify_candidate(query_h, c), candidates))

    # 검증 불가(이미지/페이지 모두 차단) 시 Vision 등급 기반 보수적 점수로 폴백.
    # 근거 없는 page/similar는 검증 실패 시 0점 - 노이즈를 결과에 올리지 않는다.
    TIER_FALLBACK = {
        "full": 85.0, "partial": 60.0, "page": 0.0,
        "full_image": 80.0, "partial_image": 55.0, "similar": 0.0,
    }
    TIER_NOTE = {
        "full": "웹에서 동일 이미지가 게시된 페이지",
        "partial": "웹에서 변형(크롭 등)된 이미지가 게시된 페이지",
        "page": "웹에서 관련 이미지가 게시된 페이지",
        "full_image": "동일 이미지 발견 (게시 페이지 미확인)",
        "partial_image": "부분 일치 이미지 발견 (게시 페이지 미확인)",
        "similar": "게시 페이지를 특정하지 못한 유사 이미지",
    }
    VERIFY_NOTE = {
        "image": "원본 대비 실측 유사도",
        "page": "페이지 직접 방문 검증 · 원본 대비 실측 유사도",
    }

    matches = []
    for cand, (measured, via) in zip(candidates, verified):
        if measured is not None:
            similarity = measured
            note = f"{TIER_NOTE[cand['tier']]} · {VERIFY_NOTE[via]} {measured}%"
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

    matches = _dedupe_matches(matches)

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
def scan(file: UploadFile = File(...)):
    # 주의: async def로 만들면 안 된다 - _scan_web의 블로킹 작업(외부 이미지 수십 장
    # 다운로드)이 이벤트 루프를 통째로 막아서, 스캔 중 /health가 응답 못 해
    # k8s liveness가 팟을 죽인다(502의 원인이었음). sync def는 FastAPI가
    # 워커 스레드에서 실행하므로 이벤트 루프가 계속 살아있다.
    content = file.file.read()
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


PLATFORM_DOMAIN_HINTS = [
    (("coupang.com",), "쿠팡"),
    (("smartstore.naver.com", "shopping.naver.com"), "네이버 스마트스토어"),
    (("instagram.com",), "인스타그램"),
    (("11st.co.kr",), "11번가"),
    (("gmarket.co.kr",), "지마켓"),
    (("auction.co.kr",), "옥션"),
    (("tiktok.com",), "틱톡"),
    (("facebook.com", "fbsbx.com"), "페이스북"),
    (("pinterest.", "pinimg.com"), "핀터레스트"),
    (("youtube.com",), "유튜브"),
]


def _detect_platform(shop: str, source_url: str | None) -> str:
    """매치의 판매처/URL에서 플랫폼을 자동으로 추정한다. 사용자가 매번 수동으로
    고르게 하는 대신, 실제로 어디서 발견됐는지 기반으로 신고서 문구를 맞춘다."""
    haystack = f"{shop} {source_url or ''}".lower()
    for domains, name in PLATFORM_DOMAIN_HINTS:
        if any(d in haystack for d in domains):
            return name
    return "오픈마켓/SNS 일반"


class ReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    match_shop: str
    match_note: str
    similarity: float
    platform: str | None = None
    source_url: str | None = None
    estimated_damage: int | None = None


# 실제 플랫폼 신고 절차 조사 결과(2026-07 기준)를 반영한 안내 문구.
# 쿠팡: 판매자신고센터(신뢰관리센터)에 상표/저작권 등록증 등 권리증명자료 + 캡처 첨부, 처리기간 12일~12주.
# 네이버 스마트스토어: 지식재산권 침해 신고센터.
PLATFORM_SUBMISSION_GUIDE = {
    "쿠팡": "쿠팡 판매자신고센터(신뢰관리센터)에 상표등록증/저작권 등록증 등 권리 증명자료와 상세페이지 캡처를 첨부해 접수. 처리에 통상 12일~12주 소요.",
    "네이버 스마트스토어": "네이버 스마트스토어 고객센터의 지식재산권 침해 신고센터를 통해 접수, 원 저작물 증빙과 침해 게시물 URL 필요.",
    "인스타그램": "Instagram 도움말 센터의 저작권 신고 양식(저작권자 본인 확인 필요)으로 접수.",
    "11번가": "11번가 고객센터 지식재산권 침해 신고 메뉴로 접수.",
    "지마켓": "지마켓 고객센터 지식재산권 침해 신고 페이지로 접수.",
    "옥션": "옥션 고객센터 지식재산권 침해 신고 페이지로 접수.",
}

@app.post("/api/report")
def generate_report(req: ReportRequest):
    platform = req.platform or _detect_platform(req.match_shop, req.source_url)
    submission_guide = PLATFORM_SUBMISSION_GUIDE.get(platform)

    # 법적 사실은 코드가 소유하는 템플릿이 전부 만든다(법 조항·금액·기한 등).
    damage_doc = (
        f"예상 피해액: {_format_amount(req.estimated_damage)}\n산정 근거: 판매가 x 월 예상판매량 {ASSUMED_MONTHLY_SALES}개(데모 가정치)\n"
        f"법적 근거: 저작권법 제125조 - 침해자가 침해행위로 얻은 이익액을 저작재산권자의 손해액으로 추정"
        if req.estimated_damage
        else "정확한 피해액 산정을 위해서는 상대방의 실제 판매 이력·매출 자료 확인이 필요합니다. "
             "플랫폼에 정보 제공을 요청하거나(저작권법 제125조 손해액 추정 규정 근거), "
             "소송상 문서제출명령으로 확보할 수 있습니다."
    )
    guide_doc = f"\n\n[신고 접수처] {submission_guide}" if submission_guide else ""
    template = (
        "---문서1---\n"
        f"[{platform} 신고 사유서]\n"
        f"본인은 '{req.product_name}' 상품 이미지의 원 판매자 겸 저작권자입니다. "
        f"'{req.match_shop}'에서 본인의 상품 이미지가 무단으로 사용되고 있음을 확인했습니다({req.match_note}). "
        f"이미지 유사도 분석 결과 {req.similarity}% 일치하여 명백한 도용으로 판단됩니다. "
        "원본 이미지, 최초 판매 게시 스크린샷, 침해 게시물 캡처를 증빙자료로 첨부하며, "
        f"해당 게시물의 판매 중지 및 이미지 삭제 조치를 요청합니다.{guide_doc}\n\n"
        "---문서2---\n"
        "[내용증명 초안]\n"
        "발신인: [본인 성명/상호/주소]\n수신인: [상대방 상호/성명/주소]\n\n"
        f"1. 발신인은 '{req.product_name}' 상품 이미지의 저작권자 겸 판매자입니다.\n"
        f"2. 수신인은 발신인의 이용 허락 없이 위 상품 이미지를 '{req.match_shop}'에서 무단 사용하여 "
        f"발신인의 저작권을 침해하고 있음을 확인하였습니다({req.match_note}, 이미지 유사도 {req.similarity}%).\n"
        "3. 본 내용증명을 수신한 날로부터 10일 이내에 해당 게시물의 판매를 중단하고 이미지를 삭제할 것과, "
        f"{('금 ' + _format_amount(req.estimated_damage) if req.estimated_damage else '피해액')}"
        "의 배상을 요청합니다.\n"
        "4. 위 기한 내 이행되지 않을 경우, 저작권법 위반에 따른 민형사상 법적 조치(고소 및 손해배상 청구 소송)를 "
        "진행할 수 있음을 알려드립니다.\n\n"
        "본 내용증명은 우체국 내용증명 우편으로 발송해 발신 사실과 도달을 증명하는 것을 권장합니다 "
        "(총 3부 작성: 발신인 보관용 / 수신인 발송용 / 우체국 보관용).\n\n"
        "---문서3---\n"
        f"[손해배상 청구 내역서]\n{damage_doc}"
    )

    # 로컬 LLM은 문장만 다듬는다. 검증 실패/모델 부재 시 템플릿 원문 그대로.
    report, ai_generated = refine_document(template, max_tokens=1400)
    return {"report": report, "ai_generated": ai_generated}


class BatchMatchItem(BaseModel):
    shop: str
    note: str
    similarity: float
    source_url: str | None = None
    estimated_damage: int | None = None


class BatchReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    matches: list[BatchMatchItem]


@app.post("/api/report/batch")
def generate_batch_report(req: BatchReportRequest):
    if not req.matches:
        raise HTTPException(400, "선택된 매치가 없습니다")

    total_damage = sum(m.estimated_damage or 0 for m in req.matches)
    listing = "\n".join(f"  - {m.shop} (유사도 {m.similarity}%)" for m in req.matches)
    damage_text = _format_amount(total_damage) if total_damage else "산정 불가(판매 이력 확인 필요)"
    template = (
        "---문서1---\n"
        f"[통합 신고 사유서]\n"
        f"본인은 '{req.product_name}' 상품 이미지의 원 판매자 겸 저작권자입니다. "
        f"아래 {len(req.matches)}곳에서 본인의 상품 이미지가 무단으로 사용되고 있음을 확인했습니다:\n{listing}\n\n"
        f"총 예상 피해액은 {damage_text}으로 산정되며, 각 게시물의 원본 이미지·침해 게시물 캡처를 "
        "증빙자료로 첨부하여 판매 중지 및 이미지 삭제 조치를 일괄 요청합니다.\n\n"
        "---문서2---\n"
        "[통합 내용증명 초안]\n"
        "발신인: [본인 성명/상호/주소]\n수신인: [각 상호/성명/주소]\n\n"
        f"1. 발신인은 '{req.product_name}' 상품 이미지의 저작권자 겸 판매자입니다.\n"
        f"2. 수신인들은 발신인의 이용 허락 없이 위 상품 이미지를 아래와 같이 무단 사용하여 "
        f"저작권을 침해하고 있음을 확인하였습니다:\n{listing}\n"
        f"3. 본 내용증명을 수신한 날로부터 10일 이내에 전 게시물의 판매를 중단하고 이미지를 삭제할 것과, "
        f"금 {damage_text}의 배상을 요청합니다.\n"
        "4. 위 기한 내 이행되지 않을 경우, 저작권법 위반에 따른 민형사상 법적 조치(고소 및 손해배상 청구 소송)를 "
        "진행할 수 있음을 알려드립니다.\n\n"
        "본 내용증명은 우체국 내용증명 우편으로 발송해 발신 사실과 도달을 증명하는 것을 권장합니다 "
        "(총 3부 작성: 발신인 보관용 / 수신인 발송용 / 우체국 보관용)."
    )

    report, ai_generated = refine_document(template, max_tokens=1800)
    return {"report": report, "ai_generated": ai_generated}


# 실제 절차 조사 결과(2026-07 기준):
# - 소액사건심판법 제2조: 소가 3,000만원 이하 민사 제1심 사건 대상 (2017.1.1.부터 시행된 기준)
# - 저작권법 제125조: 손해배상 청구 시 침해자의 이익액을 손해액으로 추정
# - 한국저작권위원회 저작권 상담센터: 창작자·소상공인 대상 무료 저작권 법률 컨설팅
# - 대한법률구조공단: 국번없이 132, 경제적 어려움이 있는 국민 대상 무료 법률상담/소송대리
LEGAL_RESOURCES = (
    "한국저작권위원회 저작권 상담센터(copyright.or.kr, 무료 저작권 법률 컨설팅), "
    "대한법률구조공단(국번없이 132, 무료 법률상담 및 요건 충족 시 무료 소송대리)"
)


class LegalGuideRequest(BaseModel):
    product_name: str
    total_matches: int
    verified_matches: int
    total_damage: int = 0
    repeated_infringement: bool = False


@app.post("/api/legal-guide")
def generate_legal_guide(req: LegalGuideRequest):
    is_small_claim = req.total_damage <= 30_000_000
    claim_line = (
        f"예상 피해액이 {_format_amount(req.total_damage)}으로 소가 3,000만원 이하 기준에 해당해, "
        "소액사건심판법 제2조에 따른 소액사건심판(1회 변론기일 원칙의 신속 절차)을 활용할 수 있습니다."
        if req.total_damage and is_small_claim
        else "예상 피해액이 3,000만원을 초과하거나 산정되지 않아, 일반 민사소송 절차 검토가 필요합니다."
    )
    template = (
        "1. 우선순위 대응 순서\n"
        "게시물 삭제가 급하다면 플랫폼 신고를 먼저 진행하고, 공식적인 경고와 증거 확보를 위해 "
        "내용증명을 함께 발송하는 것이 일반적입니다. 이후에도 해결되지 않으면 민형사 절차를 검토합니다.\n\n"
        "2. 민사/형사 대응 가능성\n"
        "저작권법 제125조에 따라 침해자가 그 침해행위로 얻은 이익액을 저작재산권자의 손해액으로 "
        "추정하여 손해배상을 청구할 수 있습니다. 사안에 따라 저작권법 위반으로 형사 고소도 가능합니다.\n\n"
        f"3. 소송 형태 판단\n{claim_line}\n"
        f"{'반복적/조직적 도용 정황이 확인되어 손해액이 커질 수 있으므로 정식 소송도 함께 검토해볼 만합니다.' if req.repeated_infringement else ''}\n\n"
        f"4. 무료 법률 지원 연결처\n{LEGAL_RESOURCES}\n\n"
        "5. 유의사항\n"
        "본 가이드는 일반적인 절차 안내이며 구체적인 법률 자문이 아닙니다. "
        "실제 진행 전 위 상담처를 통해 전문가 확인을 받으시길 권장합니다."
    )

    report, ai_generated = refine_document(template, max_tokens=1400)
    return {"report": report, "ai_generated": ai_generated}
