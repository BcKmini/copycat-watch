"""matching.py 유닛 테스트 - 정상 케이스 + 히든 엣지케이스 위주."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from ml.matching import SIMILARITY_THRESHOLD, candidate_hashes, query_hashes, similarity_from_hashes


def _sim(img_a, img_b):
    qhash, qflip, qcolor = query_hashes(img_a)
    chash, ccolor = candidate_hashes(img_b)
    return similarity_from_hashes(qhash, qflip, qcolor, chash, ccolor)


def test_identical_image_is_100_percent_similar():
    img = Image.new("RGB", (400, 400), (120, 80, 200))
    assert _sim(img, img) == 100.0


def test_flipped_image_still_matches():
    """좌우 반전된 도용 이미지도 잡아내야 한다 (워터마크 붙여서 반전해 올리는 흔한 패턴)."""
    img = Image.new("RGB", (400, 400))
    for x in range(400):
        for y in range(0, 400, 40):
            img.putpixel((x, y), (x % 256, 0, 0))
    flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
    assert _sim(img, flipped) == 100.0


def test_completely_different_images_score_low():
    solid_red = Image.new("RGB", (400, 400), (255, 0, 0))
    solid_blue = Image.new("RGB", (400, 400), (0, 0, 255))
    # 단색 이미지는 phash 저주파 성분이 우연히 겹칠 수 있어 완전히 0은 아니지만,
    # 프로덕션 임계값보다는 한참 낮아야 한다
    assert _sim(solid_red, solid_blue) < SIMILARITY_THRESHOLD


def test_similarity_is_symmetric_for_identical_pair():
    img = Image.new("RGB", (300, 300), (10, 200, 50))
    assert _sim(img, img) == _sim(img, img)


def test_tiny_1x1_image_does_not_crash():
    tiny = Image.new("RGB", (1, 1), (255, 0, 0))
    normal = Image.new("RGB", (400, 400), (255, 0, 0))
    result = _sim(tiny, normal)
    assert isinstance(result, float)


def test_grayscale_input_does_not_crash():
    gray = Image.new("L", (200, 200), 128)
    rgb = Image.new("RGB", (200, 200), (128, 128, 128))
    result = _sim(gray, rgb)
    assert isinstance(result, float)


def test_rgba_input_does_not_crash():
    rgba = Image.new("RGBA", (200, 200), (255, 0, 0, 128))
    rgb = Image.new("RGB", (200, 200), (255, 0, 0))
    result = _sim(rgba, rgb)
    assert isinstance(result, float)


def test_similarity_never_exceeds_100_or_drops_below_0():
    img_a = Image.new("RGB", (400, 400), (1, 2, 3))
    img_b = Image.new("RGB", (400, 400), (250, 249, 248))
    result = _sim(img_a, img_b)
    assert 0.0 <= result <= 100.0
