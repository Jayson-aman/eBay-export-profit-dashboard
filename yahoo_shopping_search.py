"""
yahoo_shopping_search.py — Yahoo!ショッピングAPIから商品検索＆利益判定

【取得API】Yahoo!ショッピング 商品検索(v3)
【料金】  無料（1日5万回まで）
【登録】  https://e.developer.yahoo.co.jp/
          → アプリケーションID（Client ID）発行

使い方:
    export YAHOO_APP_ID="dj00xxxxxxxxx..."
    python3 yahoo_shopping_search.py
"""

from __future__ import annotations

import os
from typing import Optional

import requests


YAHOO_API_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
DEFAULT_APP_ID = os.environ.get("YAHOO_APP_ID", "")


def search(
    keyword: str,
    min_price: int = 0,
    max_price: int = 100000,
    hits: int = 30,
    offset: int = 1,
    sort: str = "+price",
    in_stock: bool = True,
    app_id: Optional[str] = None,
) -> list[dict]:
    """
    Yahoo!ショッピングで商品検索

    Args:
        keyword: 検索キーワード
        min_price / max_price: 価格絞り込み（円）
        hits: 取得件数（最大50）
        offset: 取得開始位置（1開始）
        sort: "+price" 安い順 / "-price" 高い順
              "-review_count" レビュー多い順 / "-score" 売れ筋順
        in_stock: True なら在庫ありのみ
        app_id: Yahoo! Client ID（環境変数 YAHOO_APP_ID からも取得）
    """
    app_id = app_id or DEFAULT_APP_ID
    if not app_id:
        raise RuntimeError(
            "YAHOO_APP_ID が未設定です。\n"
            "https://e.developer.yahoo.co.jp/ でClient IDを取得し、\n"
            "  export YAHOO_APP_ID='dj00xxxxxxxxx...'\n"
            "または引数 app_id で指定してください。"
        )

    headers = {"User-Agent": f"Yahoo AppID: {app_id}"}
    params = {
        "appid": app_id,
        "query": keyword,
        "results": min(max(hits, 1), 50),
        "start": offset,
        "price_from": min_price,
        "price_to": max_price,
        "sort": sort,
        "in_stock": "true" if in_stock else "false",
    }

    r = requests.get(YAHOO_API_URL, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()

    items = []
    for it in data.get("hits", []):
        image = it.get("image") or {}
        seller = it.get("seller") or {}
        review = it.get("review") or {}

        items.append({
            "product_name": it.get("name", ""),
            "cost_jpy": int(it.get("price", 0)),
            "shop_name": seller.get("name", ""),
            "shop_code": seller.get("sellerId", ""),
            "item_url": it.get("url", ""),
            "item_code": it.get("code", ""),
            "image_url": image.get("medium") or image.get("small") or "",
            "review_avg": float(review.get("rate", 0)),
            "review_count": int(review.get("count", 0)),
            "caption": (it.get("description") or "")[:300],
            "in_stock": it.get("inStock", False),
            "point_rate": 1,  # 基本1%（詳細はAPI外）
            "condition": it.get("condition", "new"),
            "source": "yahoo_shopping",
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
    sort: str = "+price",
    app_id: Optional[str] = None,
    usdjpy: Optional[float] = None,
) -> dict:
    """
    Yahoo!ショッピング検索 → 利益判定 → ROI降順
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
            if not item["in_stock"]:
                continue
            ev = calc_unified(
                cost_jpy=item["cost_jpy"],
                sell_price_usd=estimated_sell_usd,
                weight_g=estimated_weight_g,
                category=category,
                destination=destination,
                product_name=item["product_name"][:60],
                source="yahoo_shopping",
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
                "condition": item["condition"],
            })
        except Exception:
            pass

    results.sort(key=lambda r: r["roi_pct"], reverse=True)

    return {
        "keyword": keyword,
        "total_hits": len(results),
        "go": sum(1 for r in results if r["judge"] == "GO"),
        "hold": sum(1 for r in results if r["judge"] == "HOLD"),
        "stop": sum(1 for r in results if r["judge"] == "STOP"),
        "best_roi": results[0]["roi_pct"] if results else 0,
        "results": results,
        "usdjpy": usdjpy,
    }


if __name__ == "__main__":
    if not DEFAULT_APP_ID:
        print("━" * 50)
        print("  Yahoo!ショッピングAPIデモ（APP_ID未設定のためスキップ）")
        print("━" * 50)
        print("  export YAHOO_APP_ID='dj00xxxxxxxxx...'")
    else:
        print("Yahoo!ショッピングで「九谷焼 花瓶」を検索中...")
        result = search_and_evaluate(
            keyword="九谷焼 花瓶",
            estimated_sell_usd=280,
            estimated_weight_g=1800,
            category="骨董品・陶磁器",
            max_price=30000,
        )
        print(f"\n{result['total_hits']}件ヒット "
              f"(GO {result['go']} / HOLD {result['hold']} / STOP {result['stop']})")
        for i, r in enumerate(result["results"][:5], 1):
            print(f"{i}位 [{r['judge']}] ROI {r['roi_pct']}% "
                  f"利益¥{r['profit_jpy']:,}")
            print(f"    {r['product_name'][:60]}")
            print(f"    店舗: {r['shop_name']}")
            print()
