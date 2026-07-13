"""이미지 유사도 매칭 로직. main.py(실서비스 API)와 experiments/(정확도 실험)가
같은 함수를 공유해서, 실험 결과가 실제 배포된 알고리즘을 정확히 반영하도록 한다.

phash(perceptual hash)만 쓰면 색상을 전혀 보지 않고 명암 구조만 보기 때문에,
완전히 다른 색의 단색 이미지끼리(빨간 배경 vs 파란 배경)도 100% 유사하다고
오판하는 게 테스트(tests/test_matching.py)에서 드러났다. colorhash로 색상
분포 차이를 함께 반영해 이 문제를 보정한다.
"""
import imagehash
from PIL import Image

SIMILARITY_THRESHOLD = 35  # 실험(experiments/run_experiment.py)으로 튜닝한 값
COLOR_PENALTY_PER_UNIT = 12.0  # colorhash 거리 1당 유사도 감점
MAX_COLOR_PENALTY = 70.0  # 색상 차이만으로 깎을 수 있는 최대치 (구조 일치는 여전히 반영)


def query_hashes(
    img: Image.Image,
) -> tuple[imagehash.ImageHash, imagehash.ImageHash, imagehash.ImageHash]:
    """원본/좌우반전 perceptual hash와 color hash를 함께 계산한다."""
    return (
        imagehash.phash(img),
        imagehash.phash(img.transpose(Image.FLIP_LEFT_RIGHT)),
        imagehash.colorhash(img),
    )


def candidate_hashes(img: Image.Image) -> tuple[imagehash.ImageHash, imagehash.ImageHash]:
    return imagehash.phash(img), imagehash.colorhash(img)


def similarity_from_hashes(
    query_hash: imagehash.ImageHash,
    query_flip_hash: imagehash.ImageHash,
    query_color_hash: imagehash.ImageHash,
    candidate_hash: imagehash.ImageHash,
    candidate_color_hash: imagehash.ImageHash,
) -> float:
    structure_distance = int(min(query_hash - candidate_hash, query_flip_hash - candidate_hash))
    color_distance = int(query_color_hash - candidate_color_hash)

    base_similarity = max(0.0, 100.0 - structure_distance * 3)
    color_penalty = min(color_distance * COLOR_PENALTY_PER_UNIT, MAX_COLOR_PENALTY)
    return round(max(0.0, base_similarity - color_penalty), 1)
