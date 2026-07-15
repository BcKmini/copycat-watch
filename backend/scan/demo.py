"""데모 데이터셋 로딩·상태.

Google Vision 키가 없거나 호출이 실패하면 내장 CC 라이선스 이미지셋에서 phash+colorhash로
매칭하는 폴백 모드에 쓰인다. 데모 이미지의 해시/CLIP 임베딩과 판매 정보를 메모리에 캐시한다.
"""
import json
import os
import subprocess

import imagehash
from PIL import Image

from core.config import BACKEND_ROOT, DEMO_DIR
from ml import clip_sim
from ml.matching import candidate_hashes

# fname -> (phash, colorhash)
demo_hashes: dict[str, tuple[imagehash.ImageHash, imagehash.ImageHash]] = {}
# fname -> CLIP 임베딩(있을 때만). 지연 프리컴퓨트.
demo_clip: dict = {}
# fname -> 판매 정보(shop/price/note)
listings: dict[str, dict] = {}

_demo_clip_done = False


def load_demo_hashes():
    """데모 이미지들의 해시와 판매 정보를 로드한다(앱 시작 시 1회)."""
    if not os.path.isdir(DEMO_DIR) or not os.listdir(DEMO_DIR):
        subprocess.run(
            ["python", os.path.join(BACKEND_ROOT, "gen_demo_data.py")],
            check=True,
        )
    demo_hashes.clear()
    for fname in os.listdir(DEMO_DIR):
        if fname.lower().endswith(".png"):
            path = os.path.join(DEMO_DIR, fname)
            demo_hashes[fname] = candidate_hashes(Image.open(path).convert("RGB"))

    listings.clear()
    metadata_path = os.path.join(DEMO_DIR, "metadata.json")
    if os.path.isfile(metadata_path):
        with open(metadata_path, encoding="utf-8") as f:
            listings.update(json.load(f))


def ensure_demo_clip():
    """데모 이미지의 CLIP 임베딩을 한 번만 계산해 캐시한다. CLIP 미사용 환경에선 아무 것도 안 함."""
    global _demo_clip_done
    if _demo_clip_done or not clip_sim.available():
        return
    for fname in demo_hashes:
        demo_clip[fname] = clip_sim.embed(Image.open(os.path.join(DEMO_DIR, fname)).convert("RGB"))
    _demo_clip_done = True
