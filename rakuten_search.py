"""
rakuten_search.py — 楽天市場APIから商品検索＆利益判定

【取得API】Rakuten Ichiba Item Search API
【料金】  無料（1秒1リクエスト制限）
【登録】  https://webservice.rakuten.co.jp/
          → アカウント作成 → アプリID発行（即時）

使い方:
    export RAKUTEN_APP_ID="1234567890123456789"
    python3 -c "from rakuten_search import search; \\
                for i in search('九谷焼', max_price=20000): print(i['product_name'])"
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests


RAKUTEN_API_URL = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20170706"
DEFAULT_APP_ID = os.environ.get("RAKUTEN_APP_ID", "")


def search(
    keyword: str,
    min_price: int = 0,
    max_price: int = 100000,
    hits: int = 30,
    page: int = 1,
    sort: str = "+itemPrice",
    app_id: Optional[str] = None,
) -> list[dict]:
    """
    楽天市場で商品検索

    Args:
        keyword: 検索キーワード
        min_price / max_price: 価格絞り込み（円）
        hits: 取得件数（最大30）
        page: ページ番号
        sort: ソート方法
            "+itemPrice" 安い順 / "-itemPrice" 高い順
            "-updateTimestamp" 新着順 / "-reviewCount" レビュー多い順
        app_id: 楽天アプリID（環境変数 RAKUTEN_APP_ID からも取得）

    Returns:
        商品情報のリスト
    """
    app_id = app_id or DEFAULT_APP_ID
    if not app_id:
        raise RuntimeError(
            "RAKUTEN_APP_ID が未設定です。\n"
            "https://webservice.rakuten.co.jp/ でアプリIDを取得し、\n"
            "  export RAKUTEN_APP_ID='xxxxxxxx'\n"
            "または引数 app_id で指定してください。"
        )

    params = {
        "applicationId": app_id,
        "keyword": keyword,
        "hits": min(max(hits, 1), 30),
        "page": page,
        "minPrice": min_price,
        "maxPrice": max_price,
        "format": "json",
        "sort": sort,
        "imageFlag": 1,  # 画像ありのみ
    }

    r = requests.get(RAKUTEN_API_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    items = []
    for wrapper in data.get("Items", []):
        it = wrapper.get("Item", {})
        images = it.get("mediumImageUrls", [])
        image_url = ""
        if images:
            first = images[0]
            image_url = first.get("imageUrl", "") if isinstance(first, dict) else first

        items.append({
            "product_name": it.get("itemName", ""),
            "cost_jpy": int(it.get("itemPrice", 0)),
            "shop_name": it.get("shopName", ""),
            "shop_code": it.get("shopCode", ""),
            "item_url": it.get("itemUrl", ""),
            "item_code": it.get("itemCode", ""),
            "image_url": image_url,
            "review_avg": float(it.get("reviewAverage", 0)),
            "review_count": int(it.get("reviewCount", 0)),
            "caption": (it.get("itemCaption") or "")[:300],
            "availability": int(it.get("availability", 0)),  # 1=在庫あり
            "point_rate": int(it.get("pointRate", 1)),
            "source": "rakuten",
        })

    return items


def search_and_evaluate(
    keyword: str,
    estimated_sell_usd: float,
    estimated_weight_g: float,
    category: str = "",
    destination: str = "アメリカ",
    target_roi: float = 30.0,
    min_price: int = 0,
    max_price: int = 50000,
    hits: int = 30,
    sort: str = "+itemPrice",
    app_id: Optional[str] = None,
    usdjpy: Optional[float] = None,
) -> dict:
    """
    楽天検索 → 全ヒット商品を利益判定 → ROI降順で返す
    """
    from profit_tools import calc_unified, _fetch_usdjpy

    if usdjpy is None:
        usdjpy = _fetch_usdjpy()

    items = search(
        keyword=keyword,
        min_price=min_price,
        max_price=max_price,
        hits=hits,
        sort=sort,
        app_id=app_id,
    )

    results = []
    for item in items:
        try:
            # 在庫ありのみ
            if item["availability"] != 1:
                continue
            ev = calc_unified(
                cost_jpy=item["cost_jpy"],
                sell_price_usd=estimated_sell_usd,
                weight_g=estimated_weight_g,
                category=category,
                destination=destination,
                product_name=item["product_name"][:60],
                source="rakuten",
                target_roi=target_roi,
                usdjpy=usdjpy,
            )
            results.append({
                **ev,
                "item_url": item["item_url"],
                "shop_name": item["shop_name"],
                "image_url": item["image_url"],
                "review_avg": item["review_avg"],
                "review_count": item["review_count"],
                "caption": item["caption"],
                "point_rate": item["point_rate"],
                # ポイント還元を考慮した実質コスト
                "effective_cost_jpy": int(item["cost_jpy"]
                                          * (1 - item["point_rate"] / 100)),
            })
        except Exception:
            pass

    results.sort(key=lambda r: r["roi_pct"], reverse=True)

    # サマリー
    go_count = sum(1 for r in results if r["judge"] == "GO")
    hold_count = sum(1 for r in results if r["judge"] == "HOLD")
    stop_count = sum(1 for r in results if r["judge"] == "STOP")

    return {
        "keyword": keyword,
        "total_hits": len(results),
        "go": go_count,
        "hold": hold_count,
        "stop": stop_count,
        "best_roi": results[0]["roi_pct"] if results else 0,
        "results": results,
        "usdjpy": usdjpy,
    }


if __name__ == "__main__":
    # デモ実行（RAKUTEN_APP_ID が設定されていれば）
    if not DEFAULT_APP_ID:
        print("━" * 50)
        print("  楽天APIデモ（APP_ID未設定のためスキップ）")
        print("━" * 50)
        print("以下を実行すればデモ動作します:")
        print("  export RAKUTEN_APP_ID='xxxxxxxxxxxxxxxxxxxxxx'")
        print("  python3 rakuten_search.py")
    else:
        print("楽天で「九谷焼 花瓶」を検索中...")
        result = search_and_evaluate(
            keyword="九谷焼 花瓶",
            estimated_sell_usd=280,
            estimated_weight_g=1800,
            category="骨董品・陶磁器",
            destination="アメリカ",
            target_roi=30,
            max_price=30000,
        )
        print(f"\n{result['total_hits']}件ヒット "
              f"(GO {result['go']} / HOLD {result['hold']} / STOP {result['stop']})")
        print(f"最高ROI: {result['best_roi']}%\n")
        for i, r in enumerate(result["results"][:5], 1):
            print(f"{i}位 [{r['judge']}] ROI {r['roi_pct']}% "
                  f"利益¥{r['profit_jpy']:,}")
            print(f"    {r['product_name'][:60]}")
            print(f"    店舗: {r['shop_name']} / ポイント{r['point_rate']}%")
            print(f"    {r['item_url'][:80]}")
            print()
