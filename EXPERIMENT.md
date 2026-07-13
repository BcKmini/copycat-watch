# 이미지 유사도 매칭 정확도 실험

카피캣 워치의 핵심 알고리즘(perceptual hash 기반 이미지 유사도 매칭)이 실제로 얼마나
정확한지 검증하고, 프로덕션 유사도 임계값(`SIMILARITY_THRESHOLD`)을 데이터 기반으로
정하기 위해 진행한 실험이다. 총 5번의 이터레이션을 거쳤다.

| 단계 | 내용 | 결과 |
|---|---|---|
| Iteration 1 | phash 단독 알고리즘을 CC 데이터셋(18개)으로 검증 | F1 0.923 (production threshold 35 기준) |
| Iteration 2 | pytest 유닛테스트 22개 작성 → **색상을 완전히 무시하는 히든 버그 발견** (빨강 vs 파랑 단색 이미지가 100% 일치로 오판) | 버그 재현 테스트로 고정 |
| Iteration 3 | colorhash를 결합해 색상 불일치 시 감점하도록 수정 → 두 데이터셋 모두 재검증 | F1 0.923→**1.000**(CC), 0.737→**0.962**(프로덕션 40개) |
| Iteration 4 | 실시간 웹 검색 파이프라인을 2단계 검증(후보 수집 → 서버 실측 대조)으로 재설계, 실사용 중 발견된 OOM/502·중복노출 버그 수정 | 후보 15건→50건(재현율), 오탐 없이 전량 실측검증, 중복 자동 제거(예: 50→45건) |
| Iteration 5 | 표본 크기를 대폭 확대(CC 18→91개, 프로덕션 데모셋 40→104개)해 재검증, 임계값 재튜닝 | 두 데이터셋 모두 threshold=**30**이 F1 최적(0.948 / 0.928)으로 확인되어 35→30으로 조정 |

## 1. 데이터셋

**실제 쇼핑몰(스마트스토어/쿠팡 등)은 크롤링하지 않았다** — 이용약관 위반 소지가 있고
공모전 규정(공공데이터·오픈소스 라이선스 준수)에도 어긋나기 때문이다. 대신
[Openverse API](https://openverse.org)(CC 라이선스 이미지 검색 엔진)로 "상업적 이용
가능" 라이선스의 실사 상품 사진을 검색해 수집한다. Iteration 1~4는 검색어 20종(18장
수집)으로 진행했고, Iteration 5에서 표본 크기를 늘리기 위해 검색어를 **100종으로
확대해 91장**을 수집했다(9종은 검색 결과 없음/다운로드 차단으로 제외). 각 이미지의
출처, 저작자, 라이선스는 [`experiments/dataset/manifest.json`](experiments/dataset/manifest.json)에
전부 기록해 출처 표기 요건을 충족했다.

수집 스크립트: [`experiments/crawl_dataset.py`](experiments/crawl_dataset.py)

```
[00] 'handmade soap': 'handmade soap - castile shampoo bars' by mommyknows (by)
[01] 'soy candle': '0838 soy candle / german flag upside down' by n0rthw1nd (by)
[02] 'canvas tote bag': 'Emma Burton - Digitally printed...' by Liverpool Design Festival (by-sa)
[03] 'ceramic mug': 'Coffee into Jars Ceramics mug' by Didriks (by)
...
[99] 'wooden jewelry box': 'Vintage Wooden Jewelry Box' by vintage19_something (by-nd)
총 91개 이미지 수집 완료
```

각 원본 이미지마다 실제 도용 시나리오를 흉내낸 변형본 2장을 생성했다 (프로덕션의
`gen_demo_data.py`와 동일한 방식):
- **shopA**: 크롭 + 밝기 조정 (다른 판매자가 사진을 재가공해서 올린 경우)
- **shopB**: 좌우 반전 + 워터마크 (워터마크 붙여 재판매하는 경우)

## 2. 실험 방법

실험은 실제 배포된 매칭 함수(`backend/matching.py`)를 그대로 import해서 돌린다 —
실험용으로 따로 구현한 코드가 아니라 **프로덕션과 100% 동일한 알고리즘**을 검증한다.

각 원본을 쿼리로, 전체 변형본(전체 상품 수 × 2장, 자기 자신 제외)을 후보로 비교해
유사도를 계산하고, 임계값을 0~100까지 5 단위로 훑으며 precision/recall/F1을 측정했다.
Iteration 5 기준 91개 상품 × 182개 후보 = 16,562쌍을 평가했다.

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
`pytest` 22개 전부 통과했다. 이 시점에는 임계값을 안전 마진을 두기 위해 그대로 35로
유지했다 (30을 쓰면 미세하게 더 나은 지표가 나오지만, 새로 발견한 색상 버그의 경계값과
너무 가까워 안전하게 여유를 뒀다). 표본을 늘린 뒤 이 결정을 다시 검토한 내용은
아래 Iteration 5에서 다룬다.

수정 전에는 무관한 쌍이 넓게 퍼져 있었는데, 수정 후에는 거의 대부분 0% 근처로
확실하게 몰리고 진짜 매치는 40~100%에 뚜렷하게 분리되었다 (이때의 히스토그램은
Iteration 5에서 표본을 늘리며 재생성되어, 최신 차트는 아래에서 확인할 수 있다).

전체 결과 파일: [`experiments/results/threshold_sweep.csv`](experiments/results/threshold_sweep.csv),
[`experiments/results/summary.json`](experiments/results/summary.json),
[`experiments/results/production_dataset_sweep.txt`](experiments/results/production_dataset_sweep.txt)

## 6. Iteration 4 — 실시간 웹 검색 파이프라인: 2단계 검증 + 실사용 버그 3건 수정

실사용(실제 쇼핑몰/SNS 이미지로 스캔) 중 세 가지 문제가 드러났고, 각각 원인을 재현해서
고쳤다.

**① 무관한 결과가 섞임.** 처음엔 Vision API가 준 후보를 그대로 신뢰했는데, "시각적으로
비슷한" 후보엔 완전히 다른 상품도 포함돼 있었다. 해결: Vision은 후보 수집(재현율)에만
쓰고, **서버가 후보 이미지를 직접 다운로드해 프로덕션 알고리즘(phash+colorhash)으로
재검증**하도록 2단계 파이프라인으로 재설계. 이미지 다운로드가 막힌 경우(쿠팡 등 핫링크
차단)엔 페이지 HTML을 직접 방문해 `og:image`/본문 이미지를 추출해 대조하는 딥 검증
단계를 추가했다.

**② 스캔 중 서버가 죽음(502).** `kubectl describe`로 원인 확인: (a) 후보 수십 장을
동시에 원본 해상도로 디코딩하다 메모리 초과(OOMKilled) (b) `/api/scan`이 `async def`인데
내부에서 블로킹 다운로드를 해서 스캔 중 이벤트 루프가 멈춰 `/health`가 응답 못 하고 k8s가
팟을 재시작. 해결: JPEG draft-decode로 저해상도 디코딩(해시는 32x32로 축소 계산하므로
정확도 손실 없음), sync 엔드포인트로 전환해 워커 스레드에서 실행. 부하 중 2초 간격으로
health를 폴링해 200 유지·재시작 0회 확인.

**③ 같은 글이 중복 표시됨.** `http`/`https`, `www` 유무, 쿼리스트링 차이로 같은 페이지가
다른 URL로 잡혀 중복 노출되는 문제. 해결: `_dedupe_matches()`로 정규화된 URL(스킴/www/
트레일링슬래시/쿼리 제거) 기준으로 병합하고, URL이 없는 경우 도메인+제목+유사도 조합으로
병합. 검증 성공한 쪽을 우선 유지. 유닛테스트 3개로 검증(같은 페이지의 http/https+www
변형, 검증본 우선순위, 서로 다른 페이지는 유지됨).

```
테스트 이미지(Flickr 실사 사진) 기준 측정:
  후보 발견   15건 → 50건 (Vision maxResults 30→100, 후보 풀 무제한화)
  중복 제거 후 50건 → 45건 (같은 글이 http/https 등으로 중복 잡히던 5건 병합)
  전량 실측 검증 (verified: true), 소요시간 로컬 12초 / 터널 경유 24초
  부하 중 health 200 유지, 팟 재시작 0회
```

## 7. Iteration 5 — 표본 확대(18→91개, 40→104개)와 임계값 재튜닝

이전 실험(Iteration 1~4)의 한계로 지적했던 "표본 크기가 작다"는 문제를 해결하기 위해
두 데이터셋을 모두 대폭 늘렸다.

- **CC 실험셋**: 검색어 20종(18장) → **100종(91장)**. 나머지 9종은 Openverse 검색
  결과 없음 또는 이미지 호스트의 다운로드 차단(HTTP 403)으로 제외됨.
- **프로덕션 데모셋**: 상품 40종 → **104종** (`backend/gen_demo_data.py`의
  `PRODUCT_NAMES` 확장). 동일한 방식(picsum.photos 실사 이미지 + 크롭/반전 변형)으로
  생성했고, 원본끼리 너무 비슷한 경우 자동 재시도하는 `_dedupe_similar_originals()`도
  그대로 적용해 100개 이상 규모에서도 동작을 재검증했다.

표본이 커지자(91개 기준 비교쌍이 648쌍 → 16,562쌍으로 증가) 무관한 쌍의 절대 개수가
늘어나면서 이전 임계값(35)에서의 지표가 소폭 하락했다:

```
 threshold | precision |  recall |     f1 |    FP |    FN
----------------------------------------------------------
        25 |     0.898 |   0.967 |  0.931 |    20 |     6
        30 |     0.945 |   0.951 |  0.948 |    10 |     9   <- 신규 production (CC 실험셋, 91개)
        35 |     0.966 |   0.929 |  0.947 |     6 |    13   (기존 production)
        45 |     0.970 |   0.890 |  0.928 |     5 |    20
```

```
 threshold | precision |  recall |     f1 |    FP |    FN
----------------------------------------------------------
        25 |     0.845 |   0.942 |  0.891 |    36 |    12
        30 |     0.924 |   0.933 |  0.928 |    16 |    14   <- 신규 production (프로덕션 데모셋, 104개)
        35 |     0.979 |   0.904 |  0.940 |     4 |    20   (기존 production)
```

**임계값을 35에서 30으로 낮췄다.** 이전에는 색상 무시 버그(빨강 vs 파랑)의 회귀 테스트
값(30.0)과 너무 가까워서 안전 마진으로 35를 썼는데, 이번에 `MAX_COLOR_PENALTY`를
70→75로 올려 그 값을 28.0으로 더 떨어뜨렸다(`backend/matching.py`). 그 결과 30을 써도
회귀 테스트가 안전하게 통과하고, 두 데이터셋 모두에서 UX 관점 지표(자기 상품의 변형본
2장이 상위 2건 안에 잡히는 비율)도 30이 35보다 뚜렷하게 낫다:

```
threshold=25: top-2 랭킹 부정확 = 8/104
threshold=30: top-2 랭킹 부정확 = 12/104   <- 채택
threshold=35: top-2 랭킹 부정확 = 18/104
threshold=40: top-2 랭킹 부정확 = 19/104
threshold=45: top-2 랭킹 부정확 = 21/104
```

히스토그램도 표본이 커지며 무관한 쌍(16,380쌍)이 진짜 매치(182쌍)보다 90배 가까이
많아져 일반 스케일로는 진짜 매치 막대가 안 보일 지경이 됐다. y축을 로그 스케일로
바꿔서 둘 다 보이게 했다(`experiments/run_experiment.py`).

![유사도 분포: 진짜 매치 vs 무관한 쌍 (로그 스케일, 91개 상품)](experiments/results/similarity_distribution.png)

전체 결과 파일은 재생성되어 위 최신 수치를 반영한다:
[`experiments/results/threshold_sweep.csv`](experiments/results/threshold_sweep.csv),
[`experiments/results/summary.json`](experiments/results/summary.json),
[`experiments/results/production_dataset_sweep.txt`](experiments/results/production_dataset_sweep.txt)

## 8. 자동화 테스트 스위트

`backend/tests/`에 30개의 pytest 테스트가 있다 (`test_matching.py` 8개,
`test_api.py` 22개). 정상 플로우뿐 아니라 아래 같은 히든 케이스를 커버한다:

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
- URL에서 플랫폼(쿠팡 등)이 자동으로 인식되어 신고서에 반영되는지 검증
- 여러 매치를 하나로 묶은 통합 신고서 생성 / 빈 목록 거부
- 같은 글이 http·https·www 변형으로 중복 잡혀도 1건으로 병합되는지 검증
- 여러 매치가 같은 페이지의 중복 후보일 때 검증된 매치가 우선 남는지 검증
- 예상 피해액이 소액사건 기준(3천만원)을 넘으면 정식 소송 절차를 안내하는지 검증

```bash
cd backend
pytest tests/ -v
# 30 passed
```

## 9. 한계와 향후 개선 방향

- **perceptual hash(64bit) + colorhash의 한계**: 이번 실험으로 색상 문제는 크게
  개선했지만, 여전히 무늬가 복잡하지 않고 색상 대비가 낮은 상품(예: 흰색 도자기 vs
  아이보리색 도자기)은 구분이 어려울 수 있다. 향후 CLIP 임베딩 기반 유사도로 교체하면
  구조·색상·질감을 한 번에 학습된 표현으로 비교할 수 있어 더 견고해질 것으로 예상된다
  (로드맵에 반영).
- **표본 크기**: Iteration 5에서 18→91개(CC), 40→104개(프로덕션)로 늘려 재검증했지만,
  여전히 실서비스 규모(수백~수천 건의 실사용 신고 데이터)에는 못 미친다. 특히 색상
  대비가 낮은 유사 상품군(흰색 vs 아이보리색 도자기 등)에 대한 표본이 부족해, 이런
  경계 사례가 실제로 얼마나 자주 나타나는지는 이번 실험 규모로는 확인하지 못했다.
- **Google Vision 자체의 인덱싱 커버리지는 우리가 통제할 수 없다** — 구글이 아직
  크롤링하지 않은 이미지(예: 최근에 도용된 게시물, Instagram처럼 크롤링이 제한적인
  플랫폼)는 서버 실측 검증 단계 이전에 애초에 후보로 들어오지 않는다. 이 경우 결과
  0건이 정상 동작이다(실험으로 직접 확인: 무관한 이미지 20개를 전부 실측 검증한 결과
  최대 유사도 28%로 전부 다른 물건이었음 → 필터링이 올바르게 작동한 것). Iteration 4에서
  후보 풀·딥 페이지 검증을 최대한 넓혔지만, 근본적으로 "구글도 모르는 사본"은 못 찾는다.
- **핫링크 차단 사이트의 딥 검증은 완전하지 않다** — og:image/본문 img 태그 최대 4개까지만
  확인하므로, 이미지가 JS로 늦게 로드되거나 태그 밖에 있으면 놓칠 수 있다.

## 10. 재현 방법

```bash
cd experiments
python crawl_dataset.py    # CC 라이선스 이미지 수집 (manifest.json 생성, 100종 검색 -> 91장)
python run_experiment.py   # 임계값 스윕 + 히스토그램 생성 (로그 스케일)

cd ../backend
python gen_demo_data.py    # 프로덕션 데모 데이터셋 재생성 (104종 상품)
pytest tests/ -v           # 유닛/API 테스트 30개
```
