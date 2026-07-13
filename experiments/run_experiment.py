"""정확도 실험: 실제 프로덕션 매칭 알고리즘(backend/matching.py)을 CC 라이선스
실사 데이터셋(experiments/dataset)에 대해 돌려서 정확도를 측정한다.

절차:
1. 각 원본 이미지에서 도용 변형본 2장(크롭+밝기조정 / 좌우반전+워터마크)을 생성
2. 모든 (쿼리=원본, 후보=변형본 전체) 쌍에 대해 유사도를 계산
   - 같은 상품의 변형본이면 True Positive 후보, 다른 상품의 변형본이면 False Positive 후보
3. 임계값을 0~100까지 훑으며 precision/recall/F1을 계산해 최적 임계값을 찾고,
   현재 프로덕션 임계값(SIMILARITY_THRESHOLD=35)과 비교한다
4. 결과를 터미널에 표로 출력하고, results/ 아래에 CSV·PNG로 저장한다
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

from matching import SIMILARITY_THRESHOLD, query_hashes, similarity_from_hashes
import imagehash

DATASET_DIR = os.path.join(os.path.dirname(__file__), "dataset")
ORIG_DIR = os.path.join(DATASET_DIR, "originals")
VARIANT_DIR = os.path.join(DATASET_DIR, "variants")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(VARIANT_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


def make_variants(pid, orig_path):
    orig = Image.open(orig_path).convert("RGB")
    outputs = {}

    cropped = orig.resize((400, 400)).crop((10, 10, 390, 390)).resize((400, 400))
    enhanced = Image.eval(cropped, lambda x: min(255, int(x * 1.08)))
    path_a = os.path.join(VARIANT_DIR, f"{pid}_shopA.jpg")
    enhanced.save(path_a)
    outputs["shopA"] = path_a

    flipped = orig.resize((400, 400)).transpose(Image.FLIP_LEFT_RIGHT)
    draw = ImageDraw.Draw(flipped)
    draw.rectangle([310, 360, 400, 400], fill=(0, 0, 0))
    draw.text((316, 372), "SALE", fill=(255, 255, 255))
    path_b = os.path.join(VARIANT_DIR, f"{pid}_shopB.jpg")
    flipped.save(path_b)
    outputs["shopB"] = path_b

    return outputs


def main():
    with open(os.path.join(DATASET_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"데이터셋: {len(manifest)}개 원본 (Openverse CC 라이선스 실사 이미지)\n")

    products = []
    for entry in manifest:
        pid = entry["file"].split(".")[0]
        orig_path = os.path.join(ORIG_DIR, entry["file"])
        variants = make_variants(pid, orig_path)
        products.append({"pid": pid, "query": entry["query"], "orig_path": orig_path, "variants": variants})

    # 모든 후보(변형본)의 해시를 미리 계산
    candidate_hashes = {}
    for p in products:
        for shop, path in p["variants"].items():
            candidate_hashes[f"{p['pid']}_{shop}"] = imagehash.phash(Image.open(path))

    # 쿼리(원본)마다 전체 후보와 비교
    pair_results = []  # (similarity, is_true_positive)
    for p in products:
        qhash, qflip = query_hashes(Image.open(p["orig_path"]).convert("RGB"))
        for cand_key, chash in candidate_hashes.items():
            similarity = similarity_from_hashes(qhash, qflip, chash)
            is_same_product = cand_key.startswith(f"{p['pid']}_")
            pair_results.append({
                "query": p["pid"],
                "candidate": cand_key,
                "similarity": similarity,
                "is_true_positive": is_same_product,
            })

    total_true = sum(1 for r in pair_results if r["is_true_positive"])
    total_false = sum(1 for r in pair_results if not r["is_true_positive"])
    print(f"평가 쌍: 총 {len(pair_results)}건 (진짜 매치 {total_true}건 / 무관한 쌍 {total_false}건)\n")

    # 임계값 스윕
    print(f"{'threshold':>10} | {'precision':>9} | {'recall':>7} | {'f1':>6} | {'FP':>5} | {'FN':>5}")
    print("-" * 58)
    sweep_rows = []
    best = {"f1": -1}
    for threshold in range(0, 105, 5):
        tp = sum(1 for r in pair_results if r["is_true_positive"] and r["similarity"] >= threshold)
        fn = sum(1 for r in pair_results if r["is_true_positive"] and r["similarity"] < threshold)
        fp = sum(1 for r in pair_results if not r["is_true_positive"] and r["similarity"] >= threshold)
        tn = sum(1 for r in pair_results if not r["is_true_positive"] and r["similarity"] < threshold)
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        row = {"threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
               "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}
        sweep_rows.append(row)
        marker = " <- production" if threshold == SIMILARITY_THRESHOLD else ""
        print(f"{threshold:>10} | {precision:>9.3f} | {recall:>7.3f} | {f1:>6.3f} | {fp:>5} | {fn:>5}{marker}")
        if f1 > best["f1"]:
            best = row

    print(f"\n최적 임계값(F1 기준): {best['threshold']} (F1={best['f1']})")
    prod_row = next(r for r in sweep_rows if r["threshold"] == SIMILARITY_THRESHOLD)
    print(f"현재 프로덕션 임계값: {SIMILARITY_THRESHOLD} (precision={prod_row['precision']}, recall={prod_row['recall']}, f1={prod_row['f1']})")

    with open(os.path.join(RESULTS_DIR, "threshold_sweep.csv"), "w", encoding="utf-8") as f:
        f.write("threshold,tp,fp,fn,tn,precision,recall,f1\n")
        for row in sweep_rows:
            f.write(",".join(str(row[k]) for k in ["threshold", "tp", "fp", "fn", "tn", "precision", "recall", "f1"]) + "\n")

    with open(os.path.join(RESULTS_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "dataset_size": len(products),
            "total_pairs": len(pair_results),
            "production_threshold": SIMILARITY_THRESHOLD,
            "production_metrics": prod_row,
            "best_f1_threshold": best,
        }, f, ensure_ascii=False, indent=2)

    # 유사도 분포 히스토그램
    true_sims = [r["similarity"] for r in pair_results if r["is_true_positive"]]
    false_sims = [r["similarity"] for r in pair_results if not r["is_true_positive"]]

    plt.figure(figsize=(8, 4.5))
    plt.hist(false_sims, bins=20, alpha=0.6, label="Unrelated product pairs", color="#94a3b8")
    plt.hist(true_sims, bins=20, alpha=0.7, label="Same product (original vs copied)", color="#4338ca")
    plt.axvline(SIMILARITY_THRESHOLD, color="#c0392b", linestyle="--", label=f"Production threshold ({SIMILARITY_THRESHOLD})")
    plt.xlabel("Similarity (%)")
    plt.ylabel("Number of pairs")
    plt.title("Image similarity distribution: true matches vs unrelated pairs")
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, "similarity_distribution.png"), dpi=150)
    print(f"\n히스토그램 저장: {os.path.join(RESULTS_DIR, 'similarity_distribution.png')}")


if __name__ == "__main__":
    main()
