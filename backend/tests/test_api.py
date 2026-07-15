"""API 엔드포인트 통합 테스트 - 정상 플로우 + 히든 엣지케이스(손상 파일, 초과용량,
경로탈출 시도, 필수값 누락 등).
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main


@pytest.fixture(scope="module", autouse=True)
def _load_demo_data():
    main.load_demo_hashes()


@pytest.fixture(autouse=True)
def _no_external_apis(monkeypatch):
    """테스트는 외부 API 없이 결정적으로 돌아야 한다 - 웹 검색 경로를 차단해 데모 매칭 강제."""
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)


@pytest.fixture
def client():
    return TestClient(main.app)


def _png_bytes(size=(400, 400), color=(120, 80, 200)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scan_with_valid_image_returns_matches_list(client):
    resp = client.post("/api/scan", files={"file": ("test.png", _png_bytes(), "image/png")})
    assert resp.status_code == 200
    data = resp.json()
    assert "matches" in data
    assert "mode" in data
    assert isinstance(data["matches"], list)


def test_scan_own_demo_image_finds_its_own_copies(client):
    demo_dir = Path(main.DEMO_DIR)
    original = demo_dir / "item000_original.png"
    with open(original, "rb") as f:
        resp = client.post("/api/scan", files={"file": ("item000_original.png", f, "image/png")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "demo"
    matched_files = [m["file"] for m in data["matches"]]
    assert "item000_copied_shopA.png" in matched_files


def test_scan_accepts_multiple_images_and_aggregates(client):
    """여러 장 업로드 시 각 후보를 모든 이미지와 대조해 최고 유사도를 취한다 →
    매칭되는 이미지 1장 + 무관한 이미지 1장을 함께 올려도 사본을 찾아낸다."""
    demo_dir = Path(main.DEMO_DIR)
    with open(demo_dir / "item000_original.png", "rb") as f:
        real = f.read()
    noise = _png_bytes(color=(10, 250, 10))
    resp = client.post("/api/scan", files=[
        ("file", ("item000_original.png", real, "image/png")),
        ("file", ("noise.png", noise, "image/png")),
    ])
    assert resp.status_code == 200
    data = resp.json()
    assert data["images"] == 2
    assert data["mode"] == "demo"
    matched_files = [m["file"] for m in data["matches"]]
    assert "item000_copied_shopA.png" in matched_files


def test_scan_rejects_non_image_file(client):
    resp = client.post(
        "/api/scan",
        files={"file": ("not_an_image.txt", b"this is just plain text, not an image", "text/plain")},
    )
    assert resp.status_code == 400


def test_scan_rejects_empty_file(client):
    resp = client.post("/api/scan", files={"file": ("empty.png", b"", "image/png")})
    assert resp.status_code == 400


def test_scan_rejects_truncated_image(client):
    """PIL은 open()에서 헤더만 읽고 픽셀 디코딩을 미루기 때문에, 잘린 파일이
    open()은 통과하고 나중에 처리 중 크래시할 수 있다 - 이걸 사전에 막는 회귀 테스트."""
    truncated = _png_bytes()[:20]
    resp = client.post("/api/scan", files={"file": ("truncated.png", truncated, "image/png")})
    assert resp.status_code == 400


def test_scan_rejects_oversized_file(client):
    huge = b"\x89PNG\r\n\x1a\n" + b"0" * (main.MAX_UPLOAD_BYTES + 1)
    resp = client.post("/api/scan", files={"file": ("huge.png", huge, "image/png")})
    assert resp.status_code == 413


def test_scan_requires_file_field(client):
    resp = client.post("/api/scan")
    assert resp.status_code == 422


def test_demo_image_serves_known_file(client):
    resp = client.get("/api/demo-image/item000_original.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_demo_image_rejects_unknown_file(client):
    resp = client.get("/api/demo-image/does_not_exist.png")
    assert resp.status_code == 404


def test_demo_image_rejects_path_traversal(client):
    resp = client.get("/api/demo-image/..%2F..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (404, 400)


def test_report_without_api_key_returns_three_documents(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/report",
        json={
            "product_name": "테스트 상품",
            "match_shop": "테스트 판매처",
            "match_note": "테스트 정황",
            "similarity": 88.0,
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert "문서1" in report
    assert "문서2" in report
    assert "문서3" in report


def test_report_missing_required_field_returns_422(client):
    resp = client.post("/api/report", json={"product_name": "테스트 상품"})
    assert resp.status_code == 422


def test_report_with_estimated_damage_includes_amount_in_document(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/report",
        json={
            "product_name": "테스트 상품",
            "match_shop": "테스트 판매처",
            "match_note": "테스트 정황",
            "similarity": 90.0,
            "estimated_damage": 123400,
        },
    )
    assert resp.status_code == 200
    assert "123,400원" in resp.json()["report"]


def test_report_auto_detects_platform_from_url(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/report",
        json={
            "product_name": "테스트 상품",
            "match_shop": "어떤 쇼핑몰",
            "match_note": "테스트 정황",
            "similarity": 90.0,
            "source_url": "https://www.coupang.com/vp/products/12345",
        },
    )
    assert resp.status_code == 200
    assert "쿠팡" in resp.json()["report"]


def test_batch_report_combines_multiple_matches(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/report/batch",
        json={
            "product_name": "테스트 상품",
            "matches": [
                {"shop": "판매처 A", "note": "정황 A", "similarity": 95.0, "estimated_damage": 50000},
                {"shop": "판매처 B", "note": "정황 B", "similarity": 88.0, "estimated_damage": 30000},
            ],
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert "판매처 A" in report
    assert "판매처 B" in report
    assert "문서1" in report
    assert "문서2" in report


def test_batch_report_rejects_empty_matches(client):
    resp = client.post("/api/report/batch", json={"product_name": "테스트 상품", "matches": []})
    assert resp.status_code == 400


def _match(url, sim=90.0, verified=True, shop="같은 사이트"):
    return {
        "file": url, "similarity": sim, "shop": shop, "price": "-", "note": "",
        "image_url": None, "estimated_damage": None, "source_url": url,
        "source": "web", "verified": verified,
    }


def test_dedupe_merges_same_page_different_scheme_and_www():
    matches = [
        _match("http://www.example.com/post/1"),
        _match("https://example.com/post/1/"),
    ]
    result = main.dedupe_matches(matches)
    assert len(result) == 1


def test_dedupe_keeps_verified_over_unverified_duplicate():
    matches = [
        _match("https://example.com/post/1", sim=70.0, verified=False),
        _match("https://example.com/post/1", sim=70.0, verified=True),
    ]
    result = main.dedupe_matches(matches)
    assert len(result) == 1
    assert result[0]["verified"] is True


def test_dedupe_keeps_distinct_pages():
    matches = [
        _match("https://example.com/post/1"),
        _match("https://example.com/post/2"),
        _match("https://another-site.com/post/1"),
    ]
    result = main.dedupe_matches(matches)
    assert len(result) == 3


def test_legal_guide_without_api_key_mentions_small_claims_threshold(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/legal-guide",
        json={
            "product_name": "테스트 상품",
            "total_matches": 5,
            "verified_matches": 5,
            "total_damage": 500000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_generated"] is False
    assert "소액사건심판" in data["report"]
    assert "132" in data["report"]


def test_legal_guide_includes_detected_platform_channels(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/legal-guide",
        json={
            "product_name": "수제 가죽 지갑",
            "total_matches": 2,
            "verified_matches": 2,
            "total_damage": 500000,
            "matches": [
                {"shop": "쿠팡셀러", "source_url": "https://www.coupang.com/vp/products/1"},
                {"shop": "스토어", "source_url": "https://smartstore.naver.com/x/y"},
            ],
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert "수제 가죽 지갑" in report            # 상품명 개요 반영
    assert "발견된 플랫폼별 신고 채널" in report
    assert "쿠팡" in report
    assert "네이버 스마트스토어" in report


def test_legal_guide_covers_various_platforms(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/legal-guide",
        json={
            "product_name": "P",
            "total_matches": 4,
            "verified_matches": 1,
            "total_damage": 100000,
            "matches": [
                {"shop": "a", "source_url": "https://www.daangn.com/articles/1"},
                {"shop": "b", "source_url": "https://www.tiktok.com/@x/video/1"},
                {"shop": "c", "source_url": "https://ko.aliexpress.com/item/1.html"},
                {"shop": "d", "source_url": "https://bunjang.co.kr/products/1"},
            ],
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    for p in ["당근마켓", "틱톡", "알리익스프레스", "번개장터"]:
        assert p in report


def test_batch_report_labels_platform_per_match(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/report/batch",
        json={
            "product_name": "테스트 상품",
            "matches": [
                {"shop": "A상점", "note": "n", "similarity": 95.0,
                 "source_url": "https://www.coupang.com/x", "estimated_damage": 50000},
                {"shop": "B상점", "note": "n", "similarity": 88.0,
                 "source_url": "https://www.instagram.com/y", "estimated_damage": 30000},
            ],
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert "[쿠팡]" in report            # 매치별 플랫폼 라벨
    assert "인스타그램" in report
    assert "플랫폼별 신고 접수처" in report
    assert "문서3" in report


def test_legal_guide_over_small_claims_threshold_suggests_regular_lawsuit(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post(
        "/api/legal-guide",
        json={
            "product_name": "테스트 상품",
            "total_matches": 20,
            "verified_matches": 18,
            "total_damage": 50_000_000,
            "repeated_infringement": True,
        },
    )
    assert resp.status_code == 200
    assert "일반 민사소송" in resp.json()["report"]
