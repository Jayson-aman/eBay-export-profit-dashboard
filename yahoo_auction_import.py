"""
yahoo_auction_import.py — Yahoo!オークション取込＆利益判定

【重要】Yahoo!オクはスクレイピング利用規約があるため、公式APIはありません。
        そのため以下の2方式を用意しています:

  方式A: CSVテンプレ手動取込（推奨・完全合法）
         → 候補商品を見ながらCSVにコピペ → 一括利益判定
  方式B: URL個別パーサー（実験用・利用は自己責任）
         → 1件ずつのHTMLから価格/タイトルを取得

使い方:
    # A. テンプレCSVを生成
    python3 -c "from yahoo_auction_import import make_template; \\
                make_template('yahoo_auc_template.csv')"

    # B. 1件パース（※ご自身のリサーチ利用のみ）
    python3 -c "from yahoo_auction_import import parse_url; \\
                print(parse_url('https://page.auctions.yahoo.co.jp/jp/auction/xxxxx'))"
"""

from __future__ import annotations

import csv
import re
from typing import Optional

import requests


# ══════════════════════════════════════════════════════════════
# 方式A: CSVテンプレ（推奨）
# ══════════════════════════════════════════════════════════════

YAHOO_AUC_TEMPLATE_COLS = [
    "product_name",       # 商品名（手動コピペ）
    "auction_id",         # オークションID（URLの末尾）
    "auction_url",        # 商品URL
    "cost_jpy",           # 現在価格 or 即決価格
    "sell_price_usd",     # eBay想定売値（必須・自分で調査）
    "weight_g",           # 推定重量
    "category",           # カテゴリ（profit_tools.CATEGORIES）
    "destination",        # 仕向国
    "ship_method",        # 発送方法（EMS/DHL/SAL/eパケット）
    "tariff_side",        # 関税負担 (buyer/seller)
    "target_roi",         # 目標ROI(%)
    "seller_rating",      # 出品者評価（参考）
    "bid_count",          # 入札数（参考）
    "end_time",           # 終了日時（参考）
    "notes",              # メモ
]

TEMPLATE_SAMPLES = [
    {
        "product_name": "九谷焼 古伊万里 青磁花瓶 明治期",
        "auction_id": "r123456789",
        "auction_url": "https://page.auctions.yahoo.co.jp/jp/auction/r123456789",
        "cost_jpy": 15000,
        "sell_price_usd": 320,
        "weight_g": 1800,
        "category": "骨董品・陶磁器",
        "destination": "アメリカ",
        "ship_method": "EMS",
        "tariff_side": "buyer",
        "target_roi": 30,
        "seller_rating": 4.9,
        "bid_count": 3,
        "end_time": "2026-04-25 21:30",
        "notes": "箱付き・傷なし",
    },
    {
        "product_name": "金継ぎ 志野焼 茶碗 江戸時代",
        "auction_id": "g987654321",
        "auction_url": "https://page.auctions.yahoo.co.jp/jp/auction/g987654321",
        "cost_jpy": 28000,
        "sell_price_usd": 520,
        "weight_g": 900,
        "category": "骨董品・陶磁器",
        "destination": "アメリカ",
        "ship_method": "EMS",
        "tariff_side": "buyer",
        "target_roi": 35,
        "seller_rating": 4.8,
        "bid_count": 7,
        "end_time": "2026-04-22 22:00",
        "notes": "共箱あり・鑑定書付",
    },
]


def make_template(path: str = "yahoo_auc_template.csv") -> str:
    """Yahoo!オク取込用CSVテンプレを生成"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=YAHOO_AUC_TEMPLATE_COLS)
        writer.writeheader()
        for row in TEMPLATE_SAMPLES:
            writer.writerow(row)
    return path


def evaluate_csv(
    input_csv: str,
    output_csv: Optional[str] = None,
    go_only_csv: Optional[str] = None,
    usdjpy: Optional[float] = None,
) -> dict:
    """
    Yahoo!オクCSV → 一括利益判定
    （内部的には profit_tools.batch_calc_from_csv を呼ぶ）
    """
    from profit_tools import batch_calc_from_csv
    return batch_calc_from_csv(
        input_csv=input_csv,
        output_csv=output_csv,
        go_only_csv=go_only_csv,
        usdjpy=usdjpy,
    )


# ══════════════════════════════════════════════════════════════
# 方式B: URL個別パーサー（実験・自己責任）
# ══════════════════════════════════════════════════════════════

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)


def parse_url(url: str, timeout: int = 15) -> dict:
    """
    Yahoo!オクの商品ページURLから基本情報を抽出

    注意: HTMLは変わりやすく、利用規約に従ってご自身のリサーチ目的で限定的にお使いください。
    大量アクセスは禁止です。
    """
    if "auctions.yahoo.co.jp" not in url:
        raise ValueError("Yahoo!オクのURLではありません")

    r = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout)
    r.raise_for_status()
    html = r.text

    # タイトル
    title = ""
    m = re.search(r'<title>([^<]+)</title>', html)
    if m:
        title = m.group(1).replace(" - Yahoo!オークション", "").strip()

    # OGタイトル優先
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    if m:
        title = m.group(1).strip()

    # 現在価格（JSON-LD or 本文から推定）
    current_price = 0
    buyout_price = 0

    m = re.search(r'"Price"\s*:\s*"?(\d+)', html)
    if m:
        current_price = int(m.group(1))
    m = re.search(r'"CurrentPrice"\s*:\s*"?(\d+)', html)
    if m:
        current_price = int(m.group(1))
    m = re.search(r'"BidOrBuyPrice"\s*:\s*"?(\d+)', html)
    if m:
        buyout_price = int(m.group(1))
    m = re.search(r'"price"\s*:\s*"?(\d+)', html)
    if m and not current_price:
        current_price = int(m.group(1))

    # 画像
    image_url = ""
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    if m:
        image_url = m.group(1)

    # 入札数・残り時間（ゆるいパターン）
    bid_count = 0
    m = re.search(r'"BidCount"\s*:\s*"?(\d+)', html)
    if m:
        bid_count = int(m.group(1))

    # オークションID
    auction_id = ""
    m = re.search(r'/auction/([A-Za-z0-9]+)', url)
    if m:
        auction_id = m.group(1)

    return {
        "product_name": title,
        "auction_id": auction_id,
        "auction_url": url,
        "cost_jpy": buyout_price or current_price,
        "current_price_jpy": current_price,
        "buyout_price_jpy": buyout_price,
        "bid_count": bid_count,
        "image_url": image_url,
        "source": "yahoo_auction",
    }


def parse_urls(urls: list[str]) -> list[dict]:
    """複数URLを順番にパース（レート配慮で1秒間隔）"""
    import time
    results = []
    for i, url in enumerate(urls):
        try:
            results.append(parse_url(url))
        except Exception as e:
            results.append({"auction_url": url, "error": str(e)})
        if i < len(urls) - 1:
            time.sleep(1.0)  # 1秒インターバル
    return results


def evaluate_urls(
    urls: list[str],
    estimated_sell_usd: float,
    estimated_weight_g: float,
    category: str = "",
    destination: str = "アメリカ",
    target_roi: float = 30.0,
    usdjpy: Optional[float] = None,
) -> dict:
    """
    URLリスト → パース → 利益判定
    （売値・重量は共通値を仮設定。個別指定したいなら CSV方式を推奨）
    """
    from profit_tools import calc_unified, _fetch_usdjpy

    if usdjpy is None:
        usdjpy = _fetch_usdjpy()

    parsed = parse_urls(urls)

    results = []
    for item in parsed:
        if "error" in item or not item.get("cost_jpy"):
            continue
        try:
            ev = calc_unified(
                cost_jpy=item["cost_jpy"],
                sell_price_usd=estimated_sell_usd,
                weight_g=estimated_weight_g,
                category=category,
                destination=destination,
                product_name=item["product_name"][:60],
                source="yahoo_auction",
                target_roi=target_roi,
                usdjpy=usdjpy,
            )
            results.append({
                **ev,
                "auction_url": item["auction_url"],
                "auction_id": item["auction_id"],
                "image_url": item.get("image_url", ""),
                "bid_count": item.get("bid_count", 0),
                "current_price_jpy": item.get("current_price_jpy", 0),
                "buyout_price_jpy": item.get("buyout_price_jpy", 0),
            })
        except Exception:
            pass

    results.sort(key=lambda r: r["roi_pct"], reverse=True)

    return {
        "total_hits": len(results),
        "go": sum(1 for r in results if r["judge"] == "GO"),
        "hold": sum(1 for r in results if r["judge"] == "HOLD"),
        "stop": sum(1 for r in results if r["judge"] == "STOP"),
        "results": results,
        "usdjpy": usdjpy,
    }


if __name__ == "__main__":
    import sys

    # テンプレ生成デモ
    path = make_template("yahoo_auc_template.csv")
    print(f"✓ テンプレCSV生成: {path}")
    print("  15列 × 2サンプル行")
    print("\n次にやること:")
    print("  1) Yahoo!オクで気になる商品をブラウザで開く")
    print("  2) タイトル・価格・URLをCSVに貼り付け")
    print("  3) ダッシュボードの「CSV一括判定」タブにアップロード")
    print("     または:")
    print("     python3 -c \"from yahoo_auction_import import evaluate_csv; "
          "print(evaluate_csv('yahoo_auc_template.csv', 'out.csv', 'go.csv'))\"")
