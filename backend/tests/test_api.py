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
    main._load_demo_hashes()


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
