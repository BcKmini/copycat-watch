"""데모용 샘플 이미지 생성 스크립트.
picsum.photos에서 제품별로 서로 다른 시드의 실사 이미지를 받아 '원본'으로 쓰고,
크롭/밝기조정/반전+워터마크 등으로 변형한 '도용 이미지'를 만든다.
실사 기반이라야 perceptual hash가 제품별로 뚜렷하게 구분되고,
같은 제품의 변형본끼리는 가깝게 나온다 (합성 단색 이미지는 서로 너무 비슷해서 오탐 발생함).
결과물은 git에 커밋해서 배포 시 네트워크 의존 없이 바로 쓸 수 있게 한다.
"""
import os
import urllib.request

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(__file__), "demo_data")
os.makedirs(OUT_DIR, exist_ok=True)

PRODUCTS = [
    {"id": "soap01", "seed": "copycat-soap-v2"},
    {"id": "candle01", "seed": "copycat-candle-v2"},
    {"id": "tote01", "seed": "copycat-tote-v2"},
]
UNRELATED_SEED = "copycat-mug-v2"


def fetch(seed, path):
    url = f"https://picsum.photos/seed/{seed}/400"
    urllib.request.urlretrieve(url, path)
    Image.open(path).convert("RGB").save(path)  # jpg -> png 재저장


for p in PRODUCTS:
    orig_path = os.path.join(OUT_DIR, f"{p['id']}_original.png")
    fetch(p["seed"], orig_path)
    orig = Image.open(orig_path)

    # 도용 이미지 1: 살짝 크롭 + 밝기 변경 (다른 판매자가 재가공해서 올린 느낌)
    cropped = orig.crop((10, 10, 390, 390)).resize((400, 400))
    enhancer_img = Image.eval(cropped, lambda x: min(255, int(x * 1.08)))
    enhancer_img.save(os.path.join(OUT_DIR, f"{p['id']}_copied_shopA.png"))

    # 도용 이미지 2: 좌우 반전 + 텍스트 추가 (워터마크 붙여서 재판매하는 느낌)
    flipped = orig.transpose(Image.FLIP_LEFT_RIGHT)
    draw = ImageDraw.Draw(flipped)
    draw.rectangle([50, 290, 260, 330], fill=(0, 0, 0))
    draw.text((60, 300), "SALE 50%", fill=(255, 255, 255))
    flipped.save(os.path.join(OUT_DIR, f"{p['id']}_copied_shopB.png"))

# 무관한 이미지(도용 아님, 오탐 방지 확인용)
fetch(UNRELATED_SEED, os.path.join(OUT_DIR, "unrelated_mug.png"))

print("demo data generated:", os.listdir(OUT_DIR))
