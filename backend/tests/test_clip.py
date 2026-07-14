"""CLIP 블렌드/폴백 단위 테스트. CLIP은 옵션이므로, 미설치 환경에서도 서비스가
해시 전용으로 안전하게 동작하는지(폴백)와 블렌드 산식이 맞는지 검증한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

import clip_sim
from matching import blend_similarity


def test_blend_returns_hash_when_clip_absent():
    # CLIP 유사도가 없으면(폴백) 해시 유사도를 그대로 사용한다.
    assert blend_similarity(80.0, None) == 80.0


def test_blend_averages_hash_and_clip():
    # 기본 가중치 0.5 → (80 + 100) / 2 = 90
    assert blend_similarity(80.0, 100.0) == 90.0


def test_blend_clip_can_pull_score_down():
    # CLIP이 낮으면 표시 유사도도 낮아진다(오탐 재점수). (80 + 60)/2 = 70
    assert blend_similarity(80.0, 60.0) == 70.0


def test_clip_unavailable_falls_back_to_none(monkeypatch):
    """모델 파일이 없으면 available()=False, embed()=None 이어야 한다(해시 전용)."""
    monkeypatch.setenv("CLIP_ONNX_PATH", "/nonexistent/clip-vision.onnx")
    monkeypatch.setattr(clip_sim, "_session", None)
    monkeypatch.setattr(clip_sim, "_load_failed", False)

    assert clip_sim.available() is False
    assert clip_sim.embed(Image.new("RGB", (64, 64), (120, 80, 200))) is None
