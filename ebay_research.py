"""
ebay_research.py — eBay相場リサーチ（推奨売値を自動算出）

【API】eBay Buy Browse API v1（現在出品中の商品を検索）
【認証】Application Token (Client Credentials OAuth2)
【料金】無料（1日5,000コール）
【登録】
  1. https://developer.ebay.com/ でDeveloper登録
  2. Application Keys から Production の App ID と Cert ID を取得
  3. 環境変数を設定:
       export EBAY_CLIENT_ID='YourApp-PRD-xxxxxxxxx-xxxxxxxx'
       export EBAY_CLIENT_SECRET='PRD-xxxxxxxxxxxxxxxxxxxxxxxx'

【注意】落札済み商品(sold items)データは Marketplace Insights API が必要で、
        これは事前承認制。本モジュールは現在出品中のデータのみ使用します。
"""

from __future__ import annotations

import base64
import os
import statistics
import time
from typing import Optional

import requests


# ═══════════════════════════════════════════════════════════════════
# 設定
# ═══════════════════════════════════════════════════════════════════

DEFAULT_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
DEFAULT_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")

_BASE = "https://api.ebay.com"
_TOKEN_URL = _BASE + "/identity/v1/oauth2/token"
_BROWSE_URL = _BASE + "/buy/browse/v1/item_summary/search"

# マーケットプレイスID（eBay各国）
MARKETPLACES = {
    "アメリカ":      "EBAY_US",
    "イギリス":      "EBAY_GB",
    "ドイツ":        "EBAY_DE",
    "フランス":      "EBAY_FR",
    "イタリア":      "EBAY_IT",
    "スペイン":      "EBAY_ES",
    "オーストラリア": "EBAY_AU",
    "カナダ":        "EBAY_CA",
}

# profit_tools.DESTINATION_ZONE の仕向地表記 → eBayマーケット（未登録は米国向け相場）
DESTINATION_TO_MARKETPLACE: dict[str, str] = {
    **MARKETPLACES,
    "US": "EBAY_US", "USA": "EBAY_US", "UK": "EBAY_GB", "GB": "EBAY_GB",
    "DE": "EBAY_DE", "FR": "EBAY_FR", "IT": "EBAY_IT", "ES": "EBAY_ES",
    "AU": "EBAY_AU", "NZ": "EBAY_AU",
    "中国": "EBAY_US", "韓国": "EBAY_US", "台湾": "EBAY_US",
    "タイ": "EBAY_US", "ベトナム": "EBAY_US", "メキシコ": "EBAY_US",
    "ニュージーランド": "EBAY_AU",
    "オランダ": "EBAY_DE", "ベルギー": "EBAY_DE",
    "スイス": "EBAY_DE", "スウェーデン": "EBAY_DE",
    "EU": "EBAY_DE",
}


def marketplace_for_destination(destination: str) -> str:
    """仕向地（日本語・略号）→ X-EBAY-C-MARKETPLACE-ID。未登録は EBAY_US。"""
    return DESTINATION_TO_MARKETPLACE.get(destination, "EBAY_US")


def _currency_for_marketplace(marketplace_id: str) -> str:
    """Browse API の price フィルタ用（マーケットの標準通貨）"""
    return {
        "EBAY_US": "USD",
        "EBAY_GB": "GBP",
        "EBAY_DE": "EUR",
        "EBAY_FR": "EUR",
        "EBAY_IT": "EUR",
        "EBAY_ES": "EUR",
        "EBAY_NL": "EUR",
        "EBAY_BE": "EUR",
        "EBAY_AT": "EUR",
        "EBAY_IE": "EUR",
        "EBAY_PL": "PLN",
        "EBAY_CH": "CHF",
        "EBAY_SE": "SEK",
        "EBAY_AU": "AUD",
        "EBAY_CA": "CAD",
    }.get(marketplace_id, "USD")

# 通貨→USDの概算レート（1通貨あたりUSD。定期更新推奨）
CURRENCY_TO_USD = {
    "USD": 1.0,
    "GBP": 1.27,
    "EUR": 1.09,
    "AUD": 0.66,
    "CAD": 0.74,
    "CHF": 1.12,
    "SEK": 0.095,
    "PLN": 0.25,
    "JPY": 0.0067,
}

# 状態フィルタ
CONDITIONS = {
    "新品":    "NEW",
    "中古":    "USED",
    "リファビッシュ": "CERTIFIED_REFURBISHED",
    "未指定":   "",
}


# ═══════════════════════════════════════════════════════════════════
# トークン管理（メモリキャッシュ、2時間有効）
# ═══════════════════════════════════════════════════════════════════

_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_oauth_token(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> str:
    """
    Client Credentials フローでOAuthトークンを取得
    2時間有効。キャッシュあり（期限60秒前に再取得）
    """
    client_id = client_id or DEFAULT_CLIENT_ID
    client_secret = client_secret or DEFAULT_CLIENT_SECRET
    if not client_id or not client_secret:
        raise RuntimeError(
            "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET が未設定です。\n"
            "https://developer.eBay.com/ でApp IDとCert IDを取得し、\n"
            "  export EBAY_CLIENT_ID='YourApp-PRD-xxxx'\n"
            "  export EBAY_CLIENT_SECRET='PRD-xxxxxxxxxxxx'\n"
            "または引数で指定してください。"
        )

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        _TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=15,
    )
    r.raise_for_status()
    tok = r.json()
    _token_cache["token"] = tok["access_token"]
    _token_cache["expires_at"] = now + tok.get("expires_in", 7200)
    return _token_cache["token"]


# ═══════════════════════════════════════════════════════════════════
# 検索
# ═══════════════════════════════════════════════════════════════════

def search_ebay(
    keyword: str,
    limit: int = 50,
    marketplace: str = "EBAY_US",
    condition: str = "",
    sort: str = "",
    min_price_usd: Optional[float] = None,
    max_price_usd: Optional[float] = None,
    free_shipping_only: bool = False,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> dict:
    """
    eBay Browse APIで現在出品中の商品を検索

    Returns: {"keyword", "total", "marketplace", "items": [...]}
    """
    token = get_oauth_token(client_id, client_secret)

    filters = []
    if condition:
        filters.append(f"conditions:{{{condition}}}")
    if min_price_usd is not None or max_price_usd is not None:
        cur = _currency_for_marketplace(marketplace)
        rate = CURRENCY_TO_USD.get(cur, 1.0)  # 1通貨あたりのUSD換算
        if cur == "USD":
            lo = f"{min_price_usd:.2f}" if min_price_usd is not None else ""
            hi = f"{max_price_usd:.2f}" if max_price_usd is not None else ""
        else:
            lo = (f"{(min_price_usd / rate):.2f}"
                  if min_price_usd is not None else "")
            hi = (f"{(max_price_usd / rate):.2f}"
                  if max_price_usd is not None else "")
        filters.append(f"price:[{lo}..{hi}]")
        filters.append(f"priceCurrency:{cur}")
    if free_shipping_only:
        filters.append("maxDeliveryCost:0")

    params: dict = {
        "q": keyword,
        "limit": min(max(limit, 1), 200),
    }
    if sort:
        params["sort"] = sort
    if filters:
        params["filter"] = ",".join(filters)

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
        "Accept": "application/json",
    }

    r = requests.get(_BROWSE_URL, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    items = []
    for it in data.get("itemSummaries", []):
        price = it.get("price") or {}
        seller = it.get("seller") or {}
        image = it.get("image") or {}
        shipping_options = it.get("shippingOptions") or []
        shipping_cost = 0.0
        if shipping_options:
            sc = (shipping_options[0].get("shippingCost") or {}).get("value")
            if sc:
                shipping_cost = float(sc)

        value = float(price.get("value", 0))
        currency = price.get("currency", "USD")
        value_usd = round(value * CURRENCY_TO_USD.get(currency, 1.0), 2)

        items.append({
            "title": it.get("title", ""),
            "price": value,
            "currency": currency,
            "price_usd": value_usd,
            "shipping_usd": round(shipping_cost * CURRENCY_TO_USD.get(currency, 1.0), 2),
            "total_usd": round(value_usd
                               + shipping_cost * CURRENCY_TO_USD.get(currency, 1.0), 2),
            "condition": it.get("condition", ""),
            "item_url": it.get("itemWebUrl", ""),
            "image_url": image.get("imageUrl", ""),
            "seller": seller.get("username", ""),
            "seller_feedback_pct": float(seller.get("feedbackPercentage", 0) or 0),
            "seller_feedback_count": int(seller.get("feedbackScore", 0) or 0),
            "location": (it.get("itemLocation") or {}).get("country", ""),
            "buying_options": it.get("buyingOptions", []),
        })

    return {
        "keyword": keyword,
        "total": data.get("total", 0),
        "marketplace": marketplace,
        "items": items,
    }


# ═══════════════════════════════════════════════════════════════════
# 価格分析
# ═══════════════════════════════════════════════════════════════════

def analyze_prices(
    keyword: str,
    limit: int = 50,
    marketplace: str = "EBAY_US",
    condition: str = "",
    min_price_usd: Optional[float] = None,
    max_price_usd: Optional[float] = None,
    exclude_outliers: bool = True,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> dict:
    """
    eBayで検索 → 価格分布を分析 → 推奨売値(USD)を算出

    Returns:
        {
          "keyword", "total_hits", "sampled",
          "stats": {count, min, max, mean, median, p25, p75, stdev},
          "recommended_sell_usd":  中央値×0.92（バランス）,
          "safe_sell_usd":         P25（速売）,
          "aggressive_sell_usd":   中央値（標準）,
          "premium_sell_usd":      P75（強気）,
          "items": [上位20件]
        }
    """
    result = search_ebay(
        keyword=keyword, limit=limit, marketplace=marketplace,
        condition=condition, min_price_usd=min_price_usd, max_price_usd=max_price_usd,
        client_id=client_id, client_secret=client_secret,
    )

    prices = [it["price_usd"] for it in result["items"] if it["price_usd"] > 0]
    if not prices:
        return {
            "keyword": keyword,
            "marketplace": marketplace,
            "total_hits": 0,
            "sampled": 0,
            "stats": None,
            "recommended_sell_usd": 0.0,
            "safe_sell_usd": 0.0,
            "aggressive_sell_usd": 0.0,
            "premium_sell_usd": 0.0,
            "items": [],
            "data_source": "browse_api",
        }

    # 外れ値除去（IQRの1.5倍ルール）
    if exclude_outliers and len(prices) >= 8:
        p_sorted = sorted(prices)
        q1 = p_sorted[len(p_sorted) // 4]
        q3 = p_sorted[3 * len(p_sorted) // 4]
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        filtered = [p for p in prices if lo <= p <= hi]
        if len(filtered) >= 5:
            prices = filtered

    p_sorted = sorted(prices)
    n = len(prices)
    stats = {
        "count": n,
        "min": round(min(prices), 2),
        "max": round(max(prices), 2),
        "mean": round(statistics.mean(prices), 2),
        "median": round(statistics.median(prices), 2),
        "p25": round(p_sorted[n // 4], 2),
        "p75": round(p_sorted[min(3 * n // 4, n - 1)], 2),
        "stdev": round(statistics.stdev(prices), 2) if n >= 2 else 0,
    }

    # 売値戦略
    median = stats["median"]
    p25 = stats["p25"]
    p75 = stats["p75"]
    recommended = round(median * 0.92, 2)  # 速く売れて利益も確保

    return {
        "keyword": keyword,
        "marketplace": marketplace,
        "total_hits": result["total"],
        "sampled": n,
        "stats": stats,
        "recommended_sell_usd": recommended,
        "safe_sell_usd": p25,
        "aggressive_sell_usd": median,
        "premium_sell_usd": p75,
        "items": result["items"][:20],
        "data_source": "browse_api",
    }


def format_analysis_report(a: dict) -> str:
    """分析結果を日本語レポート化"""
    if a["total_hits"] == 0 or not a["stats"]:
        return f"「{a['keyword']}」は{a['marketplace']}で出品が見つかりませんでした"

    s = a["stats"]
    lines = [
        "━" * 62,
        f"  eBay相場リサーチ: 「{a['keyword']}」 @ {a['marketplace']}",
        "━" * 62,
        f"  出品総数 : {a['total_hits']:>6,} 件",
        f"  分析対象 : {a['sampled']:>6} 件（外れ値除去後）",
        "",
        f"  【価格分布 USD】",
        f"    最安   ${s['min']:>8.2f}",
        f"    P25    ${s['p25']:>8.2f}  ← 速く売りたいならこの値",
        f"    中央値 ${s['median']:>8.2f}  ← 標準ライン",
        f"    平均   ${s['mean']:>8.2f}  （σ ${s['stdev']:.2f}）",
        f"    P75    ${s['p75']:>8.2f}  ← 余裕があるならこの値",
        f"    最高   ${s['max']:>8.2f}",
        "",
        f"  【推奨販売価格】",
        f"    🎯 バランス型:  ${a['recommended_sell_usd']:>7.2f}  （中央値×92%）",
        f"    ⚡ 速売型:      ${a['safe_sell_usd']:>7.2f}  （P25）",
        f"    💰 標準:        ${a['aggressive_sell_usd']:>7.2f}  （中央値）",
        f"    👑 強気:        ${a['premium_sell_usd']:>7.2f}  （P75）",
        "━" * 62,
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 全自動ワンショット（仕入れ元検索 × eBay相場 × 利益判定）
# ═══════════════════════════════════════════════════════════════════

def full_auto_research(
    keyword: str,
    weight_g: float,
    category: str = "",
    destination: str = "アメリカ",
    target_roi: float = 30.0,
    source: str = "rakuten",  # "rakuten" or "yahoo_shopping"
    pricing_strategy: str = "recommended",  # recommended/safe/aggressive/premium
    max_cost_jpy: int = 30000,
    hits_source: int = 30,
    hits_ebay: int = 50,
    ebay_condition: str = "",
    rakuten_app_id: Optional[str] = None,
    yahoo_app_id: Optional[str] = None,
    ebay_client_id: Optional[str] = None,
    ebay_client_secret: Optional[str] = None,
    ebay_keyword: Optional[str] = None,
    source_keyword: Optional[str] = None,
) -> dict:
    """
    キーワード1つで全自動リサーチ

    処理フロー:
      1. eBay Browse APIで該当キーワードの相場を分析
      2. 戦略に応じた売値を決定
      3. 楽天 or Yahoo!ショッピングで仕入れ候補を検索
      4. 各候補の利益を計算、ROI降順でランキング

    ebay_keyword / source_keyword:
      eBayは英語・楽天/Yahoo!は日本語、と分けたい場合に指定。
      未指定時は keyword を両方に使う。

    Returns:
        {
          "keyword",
          "ebay_analysis": {...},  # 相場分析
          "sell_price_usd": float, # 採用した売値
          "strategy": str,          # 採用戦略
          "source_results": {...}, # 仕入れ候補 + 利益判定
        }
    """
    from profit_tools import _fetch_usdjpy

    kw_ebay = (ebay_keyword or keyword).strip()
    kw_src = (source_keyword or keyword).strip()

    # 仕向地 → eBayマーケットプレイス
    marketplace = marketplace_for_destination(destination)

    # Step 1: eBay相場分析
    ebay_analysis = analyze_prices(
        keyword=kw_ebay,
        limit=hits_ebay,
        marketplace=marketplace,
        condition=ebay_condition,
        client_id=ebay_client_id,
        client_secret=ebay_client_secret,
    )

    if ebay_analysis["total_hits"] == 0:
        return {
            "keyword": keyword,
            "ebay_keyword": kw_ebay,
            "source_keyword": kw_src,
            "ebay_analysis": ebay_analysis,
            "sell_price_usd": 0,
            "strategy": pricing_strategy,
            "source_results": None,
            "error": f"eBay {marketplace} で出品が見つかりませんでした",
        }

    # Step 2: 売値決定
    strategy_key = {
        "recommended": "recommended_sell_usd",
        "safe":        "safe_sell_usd",
        "aggressive":  "aggressive_sell_usd",
        "premium":     "premium_sell_usd",
    }.get(pricing_strategy, "recommended_sell_usd")
    sell_price_usd = ebay_analysis[strategy_key]

    if sell_price_usd == 0:
        return {
            "keyword": keyword,
            "ebay_keyword": kw_ebay,
            "source_keyword": kw_src,
            "ebay_analysis": ebay_analysis,
            "sell_price_usd": 0,
            "strategy": pricing_strategy,
            "source_results": None,
            "error": "売値の決定に失敗",
        }

    # Step 3: 仕入れ元検索
    usdjpy = _fetch_usdjpy()
    if source == "rakuten":
        from rakuten_search import search_and_evaluate as rak_eval
        source_result = rak_eval(
            keyword=kw_src,
            estimated_sell_usd=sell_price_usd,
            estimated_weight_g=weight_g,
            category=category,
            destination=destination,
            target_roi=target_roi,
            max_price=max_cost_jpy,
            hits=hits_source,
            app_id=rakuten_app_id,
            usdjpy=usdjpy,
        )
    elif source == "yahoo_shopping":
        from yahoo_shopping_search import search_and_evaluate as ys_eval
        source_result = ys_eval(
            keyword=kw_src,
            estimated_sell_usd=sell_price_usd,
            estimated_weight_g=weight_g,
            category=category,
            destination=destination,
            target_roi=target_roi,
            max_price=max_cost_jpy,
            hits=hits_source,
            app_id=yahoo_app_id,
            usdjpy=usdjpy,
        )
    else:
        return {
            "keyword": keyword,
            "ebay_keyword": kw_ebay,
            "source_keyword": kw_src,
            "ebay_analysis": ebay_analysis,
            "sell_price_usd": sell_price_usd,
            "strategy": pricing_strategy,
            "source_results": None,
            "error": f"source '{source}' は未対応（rakuten/yahoo_shopping）",
        }

    return {
        "keyword": keyword,
        "ebay_keyword": kw_ebay,
        "source_keyword": kw_src,
        "ebay_analysis": ebay_analysis,
        "sell_price_usd": sell_price_usd,
        "strategy": pricing_strategy,
        "marketplace": marketplace,
        "usdjpy": usdjpy,
        "source": source,
        "source_results": source_result,
    }


# ═══════════════════════════════════════════════════════════════════
# CLIデモ
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not DEFAULT_CLIENT_ID or not DEFAULT_CLIENT_SECRET:
        print("━" * 60)
        print("  eBay Browse API デモ（未設定のためスキップ）")
        print("━" * 60)
        print("  export EBAY_CLIENT_ID='YourApp-PRD-xxxx'")
        print("  export EBAY_CLIENT_SECRET='PRD-xxxxxxxxxxxx'")
    else:
        print("【1】eBay相場分析のみ: 'Kutani vase'")
        a = analyze_prices("Kutani vase", limit=50, marketplace="EBAY_US",
                           condition="USED")
        print(format_analysis_report(a))
        print()
        print(f"【2】全自動リサーチ（eBay + 楽天 + 利益判定）")
        if not os.environ.get("RAKUTEN_APP_ID"):
            print("  楽天APP_ID未設定のためスキップ")
        else:
            r = full_auto_research(
                keyword="九谷焼 花瓶",
                weight_g=1800,
                category="骨董品・陶磁器",
                destination="アメリカ",
                target_roi=30,
                source="rakuten",
                pricing_strategy="recommended",
                max_cost_jpy=30000,
            )
            if r.get("error"):
                print(f"  エラー: {r['error']}")
            else:
                sr = r["source_results"]
                print(f"\n  eBay採用売値: ${r['sell_price_usd']} "
                      f"(戦略: {r['strategy']})")
                print(f"  楽天ヒット: {sr['total_hits']}件 "
                      f"(GO {sr['go']} / HOLD {sr['hold']} / STOP {sr['stop']})")
                for i, item in enumerate(sr["results"][:5], 1):
                    print(f"  {i}. [{item['judge']}] ROI {item['roi_pct']}% "
                          f"利益¥{item['profit_jpy']:,}")
                    print(f"     {item['product_name'][:60]}")
