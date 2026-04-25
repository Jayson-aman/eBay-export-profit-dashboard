"""各国で星マークが立っている日本製品 TOP32 を一括シミュレーション"""

from profit_tools import batch_calc_from_csv, format_batch_summary

summary = batch_calc_from_csv(
    input_csv="top32_products.csv",
    output_csv="top32_results_all.csv",
    go_only_csv="top32_results_go.csv",
)

print(format_batch_summary(summary))
print()

# 全結果を見やすくテーブル表示
print("━" * 85)
print(f"{'順位':<4} {'判定':<6} {'商品名':<36} {'ROI':>6} {'利益(¥)':>10} {'仕向地':<10}")
print("━" * 85)

# ROI順にソート
sorted_results = sorted(summary["results"],
                        key=lambda r: r["roi_pct"], reverse=True)

for i, r in enumerate(sorted_results, 1):
    name = (r.get("product_name") or "")[:34]
    dest = r.get("destination", "")[:10]
    mark = {"GO": "✅GO  ", "HOLD": "⚠️HOLD", "STOP": "⛔STOP"}.get(r["judge"], r["judge"])
    print(f"{i:<4} {mark:<6} {name:<36} {r['roi_pct']:>5.1f}% "
          f"¥{r['profit_jpy']:>9,} {dest:<10}")

print("━" * 85)
print()

# カテゴリ別のサマリー
from collections import defaultdict
by_cat = defaultdict(list)
for r in summary["results"]:
    by_cat[r["category"]].append(r)

print("【カテゴリ別 平均ROI】")
for cat, items in sorted(by_cat.items(),
                         key=lambda x: sum(r["roi_pct"] for r in x[1]) / len(x[1]),
                         reverse=True):
    avg_roi = sum(r["roi_pct"] for r in items) / len(items)
    avg_profit = sum(r["profit_jpy"] for r in items) / len(items)
    go_count = sum(1 for r in items if r["judge"] == "GO")
    print(f"  {cat:<22} 平均ROI {avg_roi:>6.1f}%  "
          f"平均利益 ¥{avg_profit:>7,.0f}  GO {go_count}/{len(items)}件")
