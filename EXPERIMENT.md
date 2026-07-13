# 이미지 유사도 매칭 정확도 실험

카피캣 워치의 핵심 알고리즘(perceptual hash 기반 이미지 유사도 매칭)이 실제로 얼마나
정확한지 검증하고, 프로덕션 유사도 임계값(`SIMILARITY_THRESHOLD`)을 데이터 기반으로
정하기 위해 진행한 실험이다. 총 3번의 이터레이션을 거쳤다.

| 단계 | 내용 | 결과 |
|---|---|---|
| Iteration 1 | phash 단독 알고리즘을 CC 데이터셋(18개)으로 검증 | F1 0.923 (production threshold 35 기준) |
| Iteration 2 | pytest 유닛테스트 22개 작성 → **색상을 완전히 무시하는 히든 버그 발견** (빨강 vs 파랑 단색 이미지가 100% 일치로 오판) | 버그 재현 테스트로 고정 |
| Iteration 3 | colorhash를 결합해 색상 불일치 시 감점하도록 수정 → 두 데이터셋 모두 재검증 | F1 0.923→**1.000**(CC), 0.737→**0.962**(프로덕션 40개) |

## 1. 데이터셋

**실제 쇼핑몰(스마트스토어/쿠팡 등)은 크롤링하지 않았다** — 이용약관 위반 소지가 있고
공모전 규정(공공데이터·오픈소스 라이선스 준수)에도 어긋나기 때문이다. 대신
[Openverse API](https://openverse.org)(CC 라이선스 이미지 검색 엔진)로 "상업적 이용
가능" 라이선스의 실사 상품 사진 20종을 검색해 **18장**을 수집했다. 각 이미지의 출처,
저작자, 라이선스는 [`experiments/dataset/manifest.json`](experiments/dataset/manifest.json)에
전부 기록해 출처 표기 요건을 충족했다.

수집 스크립트: [`experiments/crawl_dataset.py`](experiments/crawl_dataset.py)

```
[00] 'handmade soap': 'handmade soap - castile shampoo bars' by mommyknows (by)
[01] 'soy candle': '0838 soy candle / german flag upside down' by n0rthw1nd (by)
[02] 'canvas tote bag': 'Emma Burton - Digitally printed...' by Liverpool Design Festival (by-sa)
[03] 'ceramic mug': 'Coffee into Jars Ceramics mug' by Didriks (by)
...
총 18개 이미지 수집 완료
```

각 원본 이미지마다 실제 도용 시나리오를 흉내낸 변형본 2장을 생성했다 (프로덕션의
`gen_demo_data.py`와 동일한 방식):
- **shopA**: 크롭 + 밝기 조정 (다른 판매자가 사진을 재가공해서 올린 경우)
- **shopB**: 좌우 반전 + 워터마크 (워터마크 붙여 재판매하는 경우)

## 2. 실험 방법

실험은 실제 배포된 매칭 함수(`backend/matching.py`)를 그대로 import해서 돌린다 —
실험용으로 따로 구현한 코드가 아니라 **프로덕션과 100% 동일한 알고리즘**을 검증한다.

각 원본을 쿼리로, 전체 변형본(같은 상품 2장 + 다른 상품 34장)을 후보로 비교해
유사도를 계산하고, 임계값을 0~100까지 5 단위로 훑으며 precision/recall/F1을 측정했다.

실행: [`experiments/run_experiment.py`](experiments/run_experiment.py)

## 3. Iteration 1 — phash 단독 알고리즘 베이스라인

| dataset | threshold=35(production) | 최적 threshold | 비고 |
|---|---|---|---|
| CC 실험셋 (18개, 648쌍) | precision 0.857 / recall 1.000 / **F1 0.923** | 45 (F1 0.986) | |
| 프로덕션 데모셋 (40개, 3,120쌍) | precision 0.597 / recall 0.963 / **F1 0.737** | 45 (F1 0.920) | 오탐(FP) 52건 |

F1 최적값(45)을 그대로 적용하지 않은 이유: 두 데이터셋 모두 임계값을 올리면 오탐(FP)은
줄지만 **실제 도용본을 놓치는 경우(FN)가 늘었다.** 도용 탐지 도구는 오탐(사용자가 한 번
더 보고 거르면 되는 비용)보다 미탐(진짜 피해를 놓치는 비용)이 훨씬 치명적이라고 판단해,
F1 최적값 대신 recall 우선 원칙으로 threshold=35를 유지했다.

## 4. Iteration 2 — 유닛테스트로 찾은 히든 버그

`backend/tests/test_matching.py`에 정상 케이스뿐 아니라 의도적으로 "이상한 입력"을
테스트로 추가했다: 완전히 다른 색의 단색 이미지, 1x1 픽셀, 그레이스케일, RGBA, 잘린
파일 등. 이 중 하나가 실제 버그를 잡아냈다.

```
def test_completely_different_images_score_low():
    solid_red = Image.new("RGB", (400, 400), (255, 0, 0))
    solid_blue = Image.new("RGB", (400, 400), (0, 0, 255))
    assert _sim(solid_red, solid_blue) < SIMILARITY_THRESHOLD

FAILED tests/test_matching.py::test_completely_different_images_score_low
E   assert 100 < 35
```

**빨간 이미지와 파란 이미지가 100% 일치로 나왔다.** 원인: perceptual hash(phash)는
이미지를 그레이스케일로 바꾼 뒤 명암 구조(DCT 저주파 성분)만 보기 때문에, 완전히 단색인
이미지는 실제 색이 뭐든 상관없이 "변화 없음"이라는 동일한 해시가 나온다. 즉 **phash는
색상 정보를 전혀 보지 않는다** — 배경색만 다른 두 상품 사진이 100% 도용으로 오판될
수 있는 실제 리스크였다.

추가로 `/api/scan`에서 잘린(truncated) 이미지 파일이 `PIL.Image.open()`은 통과하지만
실제 픽셀 디코딩 시점에 처리되지 않은 예외로 서버 크래시를 유발할 수 있는 것도 테스트로
발견해 `query_img.load()`를 강제 호출하는 방식으로 수정했다 (`backend/main.py`).

## 5. Iteration 3 — colorhash 결합으로 수정 + 재검증

`imagehash.colorhash()`(HSV 색상 분포 기반)를 phash와 함께 계산해서, 색상이 크게
다르면 유사도를 감점하도록 `backend/matching.py`를 수정했다:

```python
structure_distance = min(phash 거리, 반전 phash 거리)
color_distance = colorhash 거리
base = max(0, 100 - structure_distance * 3)
penalty = min(color_distance * 12, 70)   # 색상만으로 최대 70점까지 감점
similarity = max(0, base - penalty)
```

수정 후 같은 두 데이터셋에 **처음부터 다시** 임계값 스윕을 실행해 회귀가 없는지
검증했다.

```
 threshold | precision |  recall |     f1 |    FP |    FN
----------------------------------------------------------
        30 |     1.000 |   1.000 |  1.000 |     0 |     0
        35 |     1.000 |   1.000 |  1.000 |     0 |     0  <- production (CC 실험셋)
        45 |     1.000 |   0.972 |  0.986 |     0 |     1
```

```
 threshold | precision |  recall |     f1 |    FP |    FN
----------------------------------------------------------
        30 |     0.963 |   0.963 |  0.963 |     3 |     3
        35 |     0.987 |   0.938 |  0.962 |     1 |     5  <- production (프로덕션 데모셋)
        45 |     0.987 |   0.925 |  0.955 |     1 |     6
```

| 지표 (threshold=35) | Iteration 1 (phash만) | Iteration 3 (phash+colorhash) |
|---|---|---|
| CC 실험셋 F1 | 0.923 | **1.000** |
| 프로덕션 데모셋 F1 | 0.737 | **0.962** |
| 프로덕션 데모셋 오탐(FP) | 52건 | **1건** |

빨강/파랑 회귀 테스트도 100 → 30.0으로 떨어져 임계값(35) 아래로 확실히 내려갔고,
`pytest` 22개 전부 통과했다. 임계값은 안전 마진을 두기 위해 그대로 35를 유지했다
(30을 쓰면 미세하게 더 나은 지표가 나오지만, 새로 발견한 색상 버그의 경계값과 너무
가까워 안전하게 여유를 뒀다).

![유사도 분포: 진짜 매치 vs 무관한 쌍](experiments/results/similarity_distribution.png)

수정 전에는 무관한 쌍이 넓게 퍼져 있었는데, 수정 후에는 거의 대부분 0% 근처로
확실하게 몰리고 진짜 매치는 40~100%에 뚜렷하게 분리된 걸 확인할 수 있다.

전체 결과 파일: [`experiments/results/threshold_sweep.csv`](experiments/results/threshold_sweep.csv),
[`experiments/results/summary.json`](experiments/results/summary.json),
[`experiments/results/production_dataset_sweep.txt`](experiments/results/production_dataset_sweep.txt)

## 6. 자동화 테스트 스위트

`backend/tests/`에 22개의 pytest 테스트가 있다 (`test_matching.py` 8개,
`test_api.py` 14개). 정상 플로우뿐 아니라 아래 같은 히든 케이스를 커버한다:

- 완전 동일 이미지 / 좌우반전 이미지 → 100% 일치
- 완전히 다른 색의 단색 이미지 → 임계값 미만 (Iteration 2에서 잡은 버그의 회귀 테스트)
- 1x1 픽셀, 그레이스케일, RGBA, 팔레트 모드 이미지 → 크래시 없이 처리
- 텍스트 파일을 이미지로 위장해서 업로드 → 400
- 빈 파일 업로드 → 400
- 잘린(truncated) 이미지 업로드 → 400 (크래시 아님)
- 10MB 초과 업로드 → 413
- `/api/demo-image`에 존재하지 않는 파일명 / 경로탈출 시도(`../../etc/passwd`) → 404
- 신고서 API 필수 필드 누락 → 422
- 신고서 API에 예상 피해액을 넘기면 생성된 문서에 실제로 그 금액이 포함되는지 검증

```bash
cd backend
pytest tests/ -v
# 22 passed
```

## 7. 한계와 향후 개선 방향

- **perceptual hash(64bit) + colorhash의 한계**: 이번 실험으로 색상 문제는 크게
  개선했지만, 여전히 무늬가 복잡하지 않고 색상 대비가 낮은 상품(예: 흰색 도자기 vs
  아이보리색 도자기)은 구분이 어려울 수 있다. 향후 CLIP 임베딩 기반 유사도로 교체하면
  구조·색상·질감을 한 번에 학습된 표현으로 비교할 수 있어 더 견고해질 것으로 예상된다
  (로드맵에 반영).
- **표본 크기**: 18~40개 상품은 통계적으로 크지 않다. 실서비스 전환 시 최소 수백 개
  규모의 실사용 신고 데이터로 재검증이 필요하다.
- **실시간 웹 검색(Google Vision API) 경로는 이 실험 대상이 아니다** — Vision API는
  구글의 자체 인덱스를 사용하므로 우리가 정확도를 통제할 수 없고, 대신 실제 동작
  검증은 대화 내 스크린샷/응답 로그로 별도 확인했다 (파이썬 로고 검색 시 실제 유튜브·
  블로그 링크 10개 이상 정확히 반환).

## 8. 재현 방법

```bash
cd experiments
python crawl_dataset.py    # CC 라이선스 이미지 수집 (manifest.json 생성)
python run_experiment.py   # 임계값 스윕 + 히스토그램 생성

cd ../backend
pytest tests/ -v           # 유닛/API 테스트 22개
```
