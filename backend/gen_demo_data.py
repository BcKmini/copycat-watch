"""데모용 샘플 이미지 생성 스크립트.
picsum.photos(무료/라이선스 프리 실사 이미지 API)에서 제품별로 서로 다른 시드의 사진을 받아
'원본'으로 쓰고, 크롭/밝기조정/반전+워터마크 등으로 변형한 '도용 이미지'를 만든다.
실제 쇼핑몰을 크롤링하지 않는다 — 이용약관/저작권 리스크가 있고 공모전 규정(공공데이터·오픈소스
라이선스 준수)에도 어긋나기 때문에, 라이선스가 명확한 합성 데모 데이터로 대체한다.
결과물(이미지 + metadata.json)은 git에 커밋해서 배포 시 네트워크 의존 없이 바로 쓸 수 있게 한다.
"""
import hashlib
import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import imagehash
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
os.makedirs(OUT_DIR, exist_ok=True)

PRODUCT_NAMES = [
    "라벤더 비누", "우드윅 소이캔들", "패브릭 에코백", "세라믹 머그컵", "스테인리스 텀블러",
    "면 파우치", "가죽 키링", "노트북 파우치", "자수 손수건", "린넨 앞치마",
    "수제 도자기 그릇", "원목 도마", "뜨개 인형", "가죽 반지갑", "천연 향초",
    "디퓨저 세트", "티코스터 세트", "천연 오일 스크럽", "마크라메 행잉플랜트", "캘리그라피 엽서",
    "리본 헤어핀", "실버 반지", "비즈 목걸이", "가죽 팔찌", "크로스백",
    "프린팅 티셔츠", "다이어리 스티커", "가죽 북마크", "우드 코스터", "소가죽 카드지갑",
    "우드 트레이", "라탄 바구니", "세라믹 화병", "유리컵 세트", "실리콘 밀폐용기",
    "면 마스크", "린넨 앞치마 세트", "미니 화분", "handmade 비누세트", "왁스타블렛",
    "천연 립밤", "고체 샴푸바", "우드 빗", "천연 수세미", "면 행주 세트",
    "리넨 냅킨", "라탄 트레이", "우드 시계", "가죽 여권지갑", "미니 크로스백",
    "천 필통", "패브릭 파우치", "니트 목도리", "손뜨개 장갑", "패치워크 방석",
    "천연 비즈왁스랩", "대나무 칫솔", "유리 디퓨저병", "도자기 접시 세트", "무명 앞치마",
    "가죽 명함지갑", "우드 트레이 세트", "라탄 조명갓", "세라믹 캔들홀더", "천연 소이왁스타블렛",
    "핸드메이드 귀걸이", "구슬 팔찌", "가죽 시계줄", "패브릭 북커버", "리넨 파우치",
    "우드 도장", "천연 아로마오일", "수제 그래놀라바", "핸드드립 드립백 세트", "수제 잼",
    "천연 발효 식초", "우드 수저받침", "라탄 컵받침", "가죽 열쇠고리", "패브릭 티코스터",
    "세라믹 비누receptacle", "우드 트레이 미니", "천연 모기퇴치 스프레이", "핸드메이드 방향제",
    "니트 파우치", "패브릭 인형", "우드 액자", "가죽 카드케이스", "라탄 바스켓 미니",
    "천연 클렌징바", "수제 캔들워머", "무명 마스크팩", "핸드메이드 브로치", "가죽 벨트",
    "우드 옷걸이", "패브릭 러그", "세라믹 티스푼", "라탄 트레이 대형", "천연 디퓨저 스틱",
    "핸드메이드 헤어밴드", "우드 트리벳", "가죽 파우치", "패브릭 쿠션커버", "니트 코스터",
]

SHOP_TEMPLATES = [
    ("OO마켓 셀러 미소상회", "원가보다 30% 저렴하게 판매 중"),
    ("스마트스토어 데일리샵", "워터마크 붙여 재판매"),
    ("OO마켓 홈라이프", "상세페이지 사진 그대로 도용"),
    ("인스타 공동구매 계정", "SNS에서 재판매 중"),
    ("OO마켓 에코라이프", "제품명만 바꿔서 등록"),
    ("스마트스토어 그린데일리", "동일 사진 좌우반전 후 사용"),
]

UNRELATED_SEEDS = [f"copycat-unrelated-{i}" for i in range(6)]

metadata = {}
_seen_hashes: set[str] = set()
_seen_lock = Lock()


def fetch(seed, path):
    """picsum은 seed가 달라도 같은 카탈로그 이미지를 줄 때가 있어서(중복 원본 발생),
    내용 해시가 이미 나온 이미지면 접미사를 바꿔 다른 이미지가 나올 때까지 재시도한다."""
    attempt = 0
    while True:
        actual_seed = seed if attempt == 0 else f"{seed}-retry{attempt}"
        url = f"https://picsum.photos/seed/{actual_seed}/400"
        urllib.request.urlretrieve(url, path)
        with open(path, "rb") as f:
            content_hash = hashlib.md5(f.read()).hexdigest()
        with _seen_lock:
            if content_hash not in _seen_hashes:
                _seen_hashes.add(content_hash)
                break
        attempt += 1
        if attempt > 10:
            break  # 너무 많이 재시도하면 포기하고 그냥 둔다
    Image.open(path).convert("RGB").save(path)  # jpg -> png 재저장


def make_product_variants(idx, name):
    """원본 사진 1장으로부터 도용 변형 2장(크롭+밝기 / 반전+워터마크)을 만든다."""
    pid = f"item{idx:03d}"
    orig = Image.open(os.path.join(OUT_DIR, f"{pid}_original.png"))
    shop_a, note_a = SHOP_TEMPLATES[idx % len(SHOP_TEMPLATES)]
    shop_b, note_b = SHOP_TEMPLATES[(idx + 1) % len(SHOP_TEMPLATES)]
    price_a = f"{(1500 + idx * 37) % 9000 + 3000:,}원"
    price_b = f"{(2200 + idx * 53) % 9000 + 3000:,}원"

    # 도용 이미지 1: 살짝 크롭 + 밝기 변경
    cropped = orig.crop((10, 10, 390, 390)).resize((400, 400))
    enhanced = Image.eval(cropped, lambda x: min(255, int(x * 1.08)))
    fname_a = f"{pid}_copied_shopA.png"
    enhanced.save(os.path.join(OUT_DIR, fname_a))
    metadata[fname_a] = {"shop": shop_a, "price": price_a, "note": note_a, "product_name": name}

    # 도용 이미지 2: 좌우 반전 + 작은 워터마크 배지 (구석에만 붙여서 원본 구도를 크게 해치지 않음)
    flipped = orig.transpose(Image.FLIP_LEFT_RIGHT)
    draw = ImageDraw.Draw(flipped)
    draw.rectangle([310, 360, 400, 400], fill=(0, 0, 0))
    draw.text((316, 372), "SALE", fill=(255, 255, 255))
    fname_b = f"{pid}_copied_shopB.png"
    flipped.save(os.path.join(OUT_DIR, fname_b))
    metadata[fname_b] = {"shop": shop_b, "price": price_b, "note": note_b, "product_name": name}


def make_product(idx, name):
    pid = f"item{idx:03d}"
    seed = f"copycat-{pid}-v3"
    orig_path = os.path.join(OUT_DIR, f"{pid}_original.png")
    fetch(seed, orig_path)
    make_product_variants(idx, name)


with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(lambda args: make_product(*args), enumerate(PRODUCT_NAMES)))
    list(pool.map(
        lambda seed: fetch(seed, os.path.join(OUT_DIR, f"unrelated_{seed.split('-')[-1]}.png")),
        UNRELATED_SEEDS,
    ))


def _dedupe_similar_originals(min_distance=28, max_rounds=5):
    """서로 다른 상품의 원본 사진이 phash상 너무 비슷하면(우연히 구도가 비슷한 스톡사진 등)
    스캔 결과가 헷갈리므로, 감지되면 해당 원본만 다른 시드로 다시 받는다."""
    for _round in range(max_rounds):
        orig_files = [f for f in os.listdir(OUT_DIR) if f.endswith("_original.png")]
        hashes = {f: imagehash.phash(Image.open(os.path.join(OUT_DIR, f))) for f in orig_files}
        conflicts = []
        for i, f1 in enumerate(orig_files):
            for f2 in orig_files[i + 1:]:
                if hashes[f1] - hashes[f2] < min_distance:
                    conflicts.append(f2)
        if not conflicts:
            return
        for fname in set(conflicts):
            idx = int(fname.split("_")[0].replace("item", ""))
            name = PRODUCT_NAMES[idx]
            fetch(f"copycat-item{idx:03d}-v3-fix{_round}", os.path.join(OUT_DIR, fname))
            make_product_variants(idx, name)


_dedupe_similar_originals()

with open(os.path.join(OUT_DIR, "metadata.json"), "w", encoding="utf-8") as f:
    json.dump(metadata, f, ensure_ascii=False, indent=2)

files = os.listdir(OUT_DIR)
print(f"demo data generated: {len(files)} files ({len(PRODUCT_NAMES)} products x 3 + {len(UNRELATED_SEEDS)} unrelated)")
