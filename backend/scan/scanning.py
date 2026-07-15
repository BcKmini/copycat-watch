"""이미지 유사도 스캔 파이프라인.

1) Google Vision Web Detection으로 인터넷 전체에서 후보 페이지/이미지를 수집(재현율 확보)
2) 각 후보 이미지를 서버가 직접 내려받아 phash+colorhash로 실측 검증·재정렬(정밀도 확보)
   - 이미지 다운로드가 막히면 게시 페이지를 방문해 딥 검증
   - 검증된 후보만 CLIP 임베딩으로 표시 유사도를 재점수(게이팅은 해시 기준 유지)
"""
import base64
import io
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

from core.config import (
    FETCH_HEADERS,
    PAGE_MAX_BYTES,
    PAGE_MAX_IMAGES,
    PAGE_TIMEOUT,
    VERIFY_MAX_BYTES,
    VERIFY_TIMEOUT,
    VERIFY_WORKERS,
    WEB_RESULT_LIMIT,
)
from core.money import estimate_damage
from ml import clip_sim
from ml.matching import (
    SIMILARITY_THRESHOLD,
    blend_similarity,
    candidate_hashes,
    query_hashes,
    similarity_from_hashes,
)
from scan import demo

logger = logging.getLogger("copycat-watch")

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)
_IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


class Query:
    """업로드된 한 장 이상의 이미지 묶음. 후보를 각 이미지와 대조해 '가장 높은'
    유사도를 취한다 — 같은 상품의 다른 각도/배경/조명 사본까지 잡기 위함(다중 이미지)."""

    def __init__(self, images: list[Image.Image]):
        self.hashes = [query_hashes(im) for im in images]
        self.clips = [clip_sim.embed(im) for im in images]  # CLIP 미사용 시 전부 None
        self._clip_present = [c for c in self.clips if c is not None]

    def best_hash_sim(self, cand_hash, cand_color) -> float:
        return max(
            similarity_from_hashes(qh[0], qh[1], qh[2], cand_hash, cand_color)
            for qh in self.hashes
        )

    def best_clip_pct(self, cand_emb) -> float | None:
        if not self._clip_present or cand_emb is None:
            return None
        return max(clip_sim.cosine_pct(q, cand_emb) for q in self._clip_present)


def _verify_candidate_image(query: Query, url: str) -> tuple[float | None, float | None]:
    """후보 이미지를 직접 내려받아 실측한다. (해시 유사도, CLIP 유사도)를 돌려주며,
    다운로드/디코딩 실패 시 (None, None). CLIP은 해시 게이트를 통과한 후보에만 계산해
    불필요한 추론을 피한다."""
    if not url or not url.startswith(("http://", "https://")):
        return None, None
    try:
        # 많은 이미지 호스트가 Referer가 없으면 핫링크로 보고 차단한다. 이미지 자신의 출처
        # 도메인을 Referer로 실어 보내면 실제로 내려받아 검증되는 후보가 늘어난다("미확인" 감소).
        p = urlparse(url)
        headers = {**FETCH_HEADERS, "Referer": f"{p.scheme}://{p.netloc}/"}
        resp = requests.get(url, headers=headers, timeout=VERIFY_TIMEOUT, stream=True)
        resp.raise_for_status()
        data = resp.raw.read(VERIFY_MAX_BYTES + 1, decode_content=True)
        if len(data) > VERIFY_MAX_BYTES:
            return None, None
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > 25_000_000:
            return None, None  # 25MP 초과 초대형 이미지는 디코딩 자체가 메모리 폭탄이라 스킵
        # 해시는 어차피 32x32로 축소해 계산하므로 저해상도 디코딩해도 결과가 같다.
        # draft는 JPEG를 디코딩 단계에서 축소해 메모리 사용을 수십 배 줄인다 (OOM 방지).
        img.draft("RGB", (512, 512))
        img.load()
        img = img.convert("RGB")
        img.thumbnail((512, 512))
        chash, ccolor = candidate_hashes(img)
        hash_sim = query.best_hash_sim(chash, ccolor)
        clip_pct = query.best_clip_pct(clip_sim.embed(img)) if hash_sim >= SIMILARITY_THRESHOLD else None
        return hash_sim, clip_pct
    except Exception:
        return None, None


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


def _verify_candidate(query: Query, cand: dict) -> tuple[float | None, float | None, str | None]:
    """후보를 실측 검증한다. 1) 후보 이미지 직접 대조 → 2) 실패 시 게시 페이지를
    직접 방문해서 페이지 안의 이미지들(og:image, 본문 img)을 하나씩 대조.
    반환: (해시 유사도 or None, CLIP 유사도 or None, 검증 방식 'image'/'page'/None)"""
    if cand.get("image_url"):
        hs, cp = _verify_candidate_image(query, cand["image_url"])
        if hs is not None:
            return hs, cp, "image"

    if cand.get("source_url"):
        try:
            page_image_urls = _extract_page_image_urls(cand["source_url"])
        except Exception:
            return None, None, None
        best = None  # (해시 유사도, CLIP 유사도)
        for img_url in page_image_urls:
            hs, cp = _verify_candidate_image(query, img_url)
            if hs is not None and (best is None or hs > best[0]):
                best = (hs, cp)
                if hs >= 90:  # 확실한 매치면 더 볼 필요 없음
                    break
        if best is not None:
            return best[0], best[1], "page"

    return None, None, None


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlparse(url.lower())
    netloc = p.netloc.removeprefix("www.")
    path = p.path.rstrip("/")
    return f"{netloc}{path}"  # 스킴/쿼리스트링/트레일링 슬래시 차이는 같은 페이지로 취급


def dedupe_matches(matches: list[dict]) -> list[dict]:
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


def scan_web(content: bytes, query: Query) -> dict | None:
    """2단계 검색 파이프라인. Vision 후보 수집 → 서버 실측 검증·재정렬.
    Vision 키가 없거나 API 실패 시 None(데모 폴백)."""
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

    # 2단계: 전 후보를 병렬 실측 검증(이미지 직접 대조가 막히면 페이지 딥 검증).
    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        verified = list(pool.map(lambda c: _verify_candidate(query, c), candidates))

    # 폴백 점수 원칙:
    # - 게시 페이지가 있는 후보(full/partial)는 검증이 막혀도 사용자가 그 페이지를 직접 열어
    #   확인할 수 있으므로 보수적 점수로 남긴다.
    # - "게시 페이지 미확인"(full_image/partial_image/similar, source_url 없음)은 페이지도 없고
    #   서버 이미지 검증도 실패했다면 확인·조치가 불가능한 근거 없는 후보다. 등급만 믿고 높은
    #   점수로 올리지 않고 0점 처리해, 실제 해시/CLIP 검증에 성공한 것만 결과에 넣는다.
    TIER_FALLBACK = {
        "full": 85.0, "partial": 60.0, "page": 0.0,
        "full_image": 0.0, "partial_image": 0.0, "similar": 0.0,
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
    for cand, (measured, clip_pct, via) in zip(candidates, verified):
        # 게이팅(채택 여부)은 해시/티어 점수로만 판단(검증된 임계값 유지). CLIP은 채택된
        # 후보의 표시 유사도를 블렌드해 점수·정렬 품질만 높인다.
        if measured is not None:
            gate_sim = measured
            note = f"{TIER_NOTE[cand['tier']]} · {VERIFY_NOTE[via]} {measured}%"
            if clip_pct is not None:
                note += " · CLIP 임베딩 보정"
        else:
            gate_sim = TIER_FALLBACK[cand["tier"]]
            note = f"{TIER_NOTE[cand['tier']]} · 이미지 직접 검증 불가(사이트 차단)"
        if gate_sim < SIMILARITY_THRESHOLD:
            continue
        matches.append({
            "file": cand["key"],
            "similarity": blend_similarity(gate_sim, clip_pct),
            "shop": cand["title"],
            "price": "-",
            "note": note,
            "image_url": cand["image_url"],
            "estimated_damage": None,
            "source_url": cand["source_url"],
            "source": "web",
            "verified": measured is not None,
        })

    matches = dedupe_matches(matches)
    # 실측 검증된 결과를 우선하고, 같은 그룹 안에서는 유사도 내림차순
    matches.sort(key=lambda m: (-m["verified"], -m["similarity"]))
    matches = matches[:WEB_RESULT_LIMIT]

    best_guess = web.get("bestGuessLabels", [])
    label = best_guess[0]["label"] if best_guess else None
    return {"matches": matches, "label": label}


def scan_demo(query: Query) -> list[dict]:
    """Vision 폴백. 내장 데모 데이터셋에서 phash+colorhash(+CLIP)로 매칭한다."""
    demo.ensure_demo_clip()
    matches = []
    for fname, (cand_hash, cand_color_hash) in demo.demo_hashes.items():
        if "original" in fname or "unrelated" in fname:
            continue
        hash_sim = query.best_hash_sim(cand_hash, cand_color_hash)
        if hash_sim >= SIMILARITY_THRESHOLD:
            clip_pct = query.best_clip_pct(demo.demo_clip.get(fname))
            listing = demo.listings.get(fname, {"shop": "알 수 없는 판매처", "price": "-", "note": ""})
            matches.append({
                "file": fname,
                "similarity": blend_similarity(hash_sim, clip_pct),
                "shop": listing["shop"],
                "price": listing["price"],
                "note": listing["note"],
                "image_url": f"/api/demo-image/{fname}",
                "estimated_damage": estimate_damage(listing["price"]),
                "source_url": None,
                "source": "demo",
            })

    matches.sort(key=lambda m: -m["similarity"])
    return matches
