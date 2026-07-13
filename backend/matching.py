"""이미지 유사도 매칭 로직. main.py(실서비스 API)와 experiments/(정확도 실험)가
같은 함수를 공유해서, 실험 결과가 실제 배포된 알고리즘을 정확히 반영하도록 한다."""
import imagehash
from PIL import Image

SIMILARITY_THRESHOLD = 35  # 실험(experiments/run_experiment.py)으로 튜닝한 값


def query_hashes(img: Image.Image) -> tuple[imagehash.ImageHash, imagehash.ImageHash]:
    """원본과 좌우반전 해시를 함께 계산해, 반전된 도용 이미지도 잡아낸다."""
    return imagehash.phash(img), imagehash.phash(img.transpose(Image.FLIP_LEFT_RIGHT))


def similarity_from_hashes(
    query_hash: imagehash.ImageHash,
    query_flip_hash: imagehash.ImageHash,
    candidate_hash: imagehash.ImageHash,
) -> float:
    distance = int(min(query_hash - candidate_hash, query_flip_hash - candidate_hash))
    return round(max(0, 100 - distance * 3), 1)
