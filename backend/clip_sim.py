"""CLIP(ViT-B/32) 이미지 임베딩 유사도. phash+colorhash가 놓치는 '의미적' 유사도
(같은 상품의 다른 각도·배경·리터칭)를 보강하는 신호로 쓴다.

설계 원칙 — matching.py의 검증된 해시 파이프라인은 그대로 두고, CLIP은 '추가 신호'다:
- 후보 채택 여부(임계값 게이팅)는 해시 유사도가 결정한다(EXPERIMENT.md 검증 결과 유지).
- CLIP은 채택된 후보의 표시 유사도를 재점수·재정렬하는 데만 쓰인다 → 오탐/누락 회귀 없음.

경량성/폴백:
- torch 대신 onnxruntime(CPU)로 구동한다. 모델은 Cloud Run 이미지에 내장(CLIP_ONNX_PATH).
- onnxruntime 미설치·모델 부재·로드 실패 시 조용히 None을 돌려주고, 서비스는 해시만으로
  동작한다(로컬 개발/k3d는 CLIP 없이 그대로 돌아간다).
"""
import os
import sys
import threading

import numpy as np
from PIL import Image

_lock = threading.Lock()
_session = None
_load_failed = False

# OpenAI CLIP ViT-B/32 전처리 상수(고정값).
_CLIP_SIZE = 224
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

# 코사인 유사도 → 0~100 매핑 구간. 같은/거의 같은 이미지는 0.95+, 무관 이미지는 0.6 이하로
# 떨어지는 CLIP 분포에 맞춰 이 구간을 100~0으로 선형 매핑한다.
_COS_HIGH = 0.95
_COS_LOW = 0.60


def _get_session():
    global _session, _load_failed
    if _session is not None or _load_failed:
        return _session
    with _lock:
        if _session is not None or _load_failed:
            return _session
        model_path = os.environ.get("CLIP_ONNX_PATH", "/models/clip-vision.onnx")
        if not os.path.exists(model_path):
            _load_failed = True
            print(f"[clip] 모델 파일 없음: {model_path} → 해시 전용 폴백", file=sys.stderr)
            return None
        try:
            import onnxruntime as ort

            _session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        except Exception as e:
            _load_failed = True
            print(f"[clip] 로드 실패({type(e).__name__}): {e} → 해시 전용 폴백", file=sys.stderr)
    return _session


def available() -> bool:
    return _get_session() is not None


def _preprocess(img: Image.Image) -> np.ndarray:
    """CLIP 표준 전처리: 짧은 변 224로 리사이즈 → 224 센터크롭 → 정규화 → (1,3,224,224)."""
    img = img.convert("RGB")
    w, h = img.size
    scale = _CLIP_SIZE / min(w, h)
    img = img.resize((round(w * scale), round(h * scale)), Image.BICUBIC)
    w, h = img.size
    left, top = (w - _CLIP_SIZE) // 2, (h - _CLIP_SIZE) // 2
    img = img.crop((left, top, left + _CLIP_SIZE, top + _CLIP_SIZE))

    arr = (np.asarray(img, dtype=np.float32) / 255.0 - _CLIP_MEAN) / _CLIP_STD
    return np.transpose(arr, (2, 0, 1))[np.newaxis, ...].astype(np.float32)


def embed(img: Image.Image) -> np.ndarray | None:
    """이미지의 L2 정규화된 CLIP 임베딩을 돌려준다. 사용 불가 시 None."""
    session = _get_session()
    if session is None:
        return None
    try:
        pixel_values = _preprocess(img)
        input_name = session.get_inputs()[0].name
        out_names = [o.name for o in session.get_outputs()]
        outputs = session.run(None, {input_name: pixel_values})
        named = dict(zip(out_names, outputs))
        # 투영된 이미지 임베딩(image_embeds)을 우선하고, 없으면 (1, D) 형태의 벡터 출력을 쓴다.
        vec = None
        for name, out in named.items():
            if "image_embed" in name.lower() or "embed" in name.lower():
                vec = np.asarray(out)
                break
        if vec is None:
            for out in outputs:
                a = np.asarray(out)
                if a.ndim == 2 and a.shape[0] == 1:
                    vec = a
                    break
        if vec is None:
            return None
        vec = np.asarray(vec).reshape(-1).astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else None
    except Exception as e:
        print(f"[clip] 임베딩 실패({type(e).__name__}): {e}", file=sys.stderr)
        return None


def cosine_pct(a: np.ndarray, b: np.ndarray) -> float:
    """정규화된 두 임베딩의 코사인 유사도를 0~100%로 매핑한다."""
    cos = float(np.dot(a, b))
    pct = (cos - _COS_LOW) / (_COS_HIGH - _COS_LOW) * 100.0
    return round(min(100.0, max(0.0, pct)), 1)
