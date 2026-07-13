"""정확도 실험용 데이터셋 수집 스크립트.

실제 쇼핑몰(스마트스토어/쿠팡 등)은 크롤링하지 않는다 - 이용약관 위반 소지가 있고
공모전 규정(오픈소스/공공데이터 라이선스 준수)에도 어긋난다.
대신 Openverse API(openverse.org, CC 라이선스 이미지 검색 엔진)로 실사 상품 사진을
'상업적 이용 가능' 라이선스로 한정해 수집한다. 각 이미지의 출처/저작자/라이선스를
manifest.json에 함께 기록해 출처 표기 요건을 충족한다.
"""
import json
import os
import time
import urllib.parse
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(__file__), "dataset")
ORIG_DIR = os.path.join(OUT_DIR, "originals")
os.makedirs(ORIG_DIR, exist_ok=True)

QUERIES = [
    "handmade soap", "soy candle", "canvas tote bag", "ceramic mug", "leather wallet",
    "wooden cutting board", "knit doll", "scented diffuser", "linen apron", "beaded necklace",
    "silver ring", "leather bracelet", "crossbody bag", "printed t-shirt", "wooden coaster",
    "glass vase", "rattan basket", "macrame plant hanger", "calligraphy postcard", "hair clip",
]

HEADERS = {"User-Agent": "CopycatWatch-Research/1.0 (educational experiment; contact: contest submission)"}


def search_one(query):
    url = (
        "https://api.openverse.org/v1/images/"
        f"?q={urllib.parse.quote(query)}&license_type=commercial&page_size=5&mature=false"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    for result in data.get("results", []):
        img_url = result.get("url")
        if not img_url:
            continue
        return {
            "query": query,
            "image_url": img_url,
            "title": result.get("title"),
            "creator": result.get("creator"),
            "license": result.get("license"),
            "license_version": result.get("license_version"),
            "source": result.get("source"),
            "foreign_landing_url": result.get("foreign_landing_url"),
        }
    return None


def download(url, path):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read()
    with open(path, "wb") as f:
        f.write(content)


def main():
    manifest = []
    for idx, query in enumerate(QUERIES):
        try:
            meta = search_one(query)
            if meta is None:
                print(f"[{idx:02d}] {query!r}: 결과 없음, 스킵")
                continue
            fname = f"item{idx:03d}.jpg"
            download(meta["image_url"], os.path.join(ORIG_DIR, fname))
            meta["file"] = fname
            manifest.append(meta)
            print(f"[{idx:02d}] {query!r}: {meta['title']!r} by {meta['creator']} ({meta['license']}) -> {fname}")
        except Exception as e:
            print(f"[{idx:02d}] {query!r}: 실패 ({e})")
        time.sleep(0.3)  # API 매너

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n총 {len(manifest)}개 이미지 수집 완료 -> {OUT_DIR}")


if __name__ == "__main__":
    main()
