"""
sold_price_csv.py — Terapeak / eBay Sold 手動取込 → 落札に近い価格分布を分析

仕様: TERAPEAK_AND_SOLD_SPEC.md

Browse API（現在出品）とは独立し、CSV の数値列から中央値・推奨売値を算出する。
出力 dict のキーは ebay_research.analyze_prices と揃え、ダッシュボードで共通表示可能。
"""

from __future__ import annotations

import csv
import io
import statistics
from typing import Any, BinaryIO, Optional, TextIO

from ebay_research import CURRENCY_TO_USD


# 列名エイリアス（小文字化・前後空白除去後に照合）
ALIASES_TOTAL = ("total_usd", "total", "落札合計", "gross_usd")
ALIASES_SOLD = (
    "sold_price_usd", "sold_price", "price_usd", "price",
    "落札価格", "売価", "final_price",
)
ALIASES_ITEM = ("item_price", "item_price_usd", "hammer", "商品価格")
ALIASES_SHIP = ("shipping_usd", "shipping", "送料", "buyer_shipping")
ALIASES_CURRENCY = ("currency", "通貨", "curr")
ALIASES_TITLE = ("title", "product_name", "商品名", "name")
ALIASES_DATE = ("sold_date", "date", "落札日")
ALIASES_NOTES = ("notes", "memo", "メモ")
ALIASES_SOURCE = ("source", "データ元")


def _norm_key(s: str) -> str:
    return s.strip().lower().replace("\ufeff", "")


def _find_column(headers: list[str], aliases: tuple[str, ...]) -> Optional[str]:
    hmap = {_norm_key(h): h for h in headers}
    for a in aliases:
        if a in hmap:
            return hmap[a]
        na = _norm_key(a)
        if na in hmap:
            return hmap[na]
    return None


def _to_float(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(str(x).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _to_usd(amount: float, currency: str) -> float:
    cur = (currency or "USD").upper().strip()
    rate = CURRENCY_TO_USD.get(cur, 1.0)
    return round(amount * rate, 2)


def _iqr_filter(prices: list[float]) -> list[float]:
    if len(prices) < 8:
        return prices
    p_sorted = sorted(prices)
    q1 = p_sorted[len(p_sorted) // 4]
    q3 = p_sorted[3 * len(p_sorted) // 4]
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [p for p in prices if lo <= p <= hi]
    if len(filtered) >= 5:
        return filtered
    return prices


def _stats_and_recommendations(
    prices: list[float],
    exclude_outliers: bool = True,
) -> tuple[dict, dict]:
    """ prices: USD 済みの正のリスト """
    if not prices:
        return {}, {}

    work = list(prices)
    if exclude_outliers:
        work = _iqr_filter(work)

    p_sorted = sorted(work)
    n = len(p_sorted)
    stats = {
        "count": n,
        "min": round(min(p_sorted), 2),
        "max": round(max(p_sorted), 2),
        "mean": round(statistics.mean(p_sorted), 2),
        "median": round(statistics.median(p_sorted), 2),
        "p25": round(p_sorted[n // 4], 2),
        "p75": round(p_sorted[min(3 * n // 4, n - 1)], 2),
        "stdev": round(statistics.stdev(p_sorted), 2) if n >= 2 else 0.0,
    }
    median = stats["median"]
    p25 = stats["p25"]
    p75 = stats["p75"]
    rec = {
        "recommended_sell_usd": round(median * 0.92, 2),
        "safe_sell_usd": p25,
        "aggressive_sell_usd": median,
        "premium_sell_usd": p75,
    }
    return stats, rec


def _row_to_usd(row: dict[str, str], headers: list[str]) -> tuple[Optional[float], dict[str, Any]]:
    """1行から分析用 USD 金額と表示用メタを返す。"""

    def getv(*aliases: str) -> Optional[str]:
        for a in aliases:
            for h in headers:
                if _norm_key(h) == _norm_key(a):
                    return row.get(h)
        return None

    cur = getv(*ALIASES_CURRENCY) or "USD"

    t = _to_float(getv(*ALIASES_TOTAL))
    if t is not None and t > 0:
        return _to_usd(t, cur), {"basis": "total_usd", "currency": cur}

    ship = _to_float(getv(*ALIASES_SHIP)) or 0.0

    ip = _to_float(getv(*ALIASES_ITEM))
    if ip is not None and ip > 0:
        total = ip + ship
        return _to_usd(total, cur), {"basis": "item_plus_shipping", "currency": cur}

    sold_val: Optional[float] = None
    for key in ALIASES_SOLD:
        col = _find_column(headers, (key,))
        if col:
            sold_val = _to_float(row.get(col))
            if sold_val is not None and sold_val > 0:
                break
    if sold_val is not None and sold_val > 0:
        total = sold_val + ship
        if ship > 0:
            return _to_usd(total, cur), {"basis": "sold_price_plus_shipping", "currency": cur}
        return _to_usd(sold_val, cur), {"basis": "sold_price", "currency": cur}

    return None, {}


def parse_sold_rows(
    rows: list[dict[str, str]],
    headers: list[str],
) -> tuple[list[float], list[dict[str, Any]], int]:
    """
    Returns:
        prices_usd, row_details (for table), skipped_count
    """
    prices: list[float] = []
    details: list[dict[str, Any]] = []
    skipped = 0

    for i, row in enumerate(rows):
        usd, meta = _row_to_usd(row, headers)
        if usd is None or usd <= 0:
            skipped += 1
            continue
        prices.append(usd)
        title_col = _find_column(headers, ALIASES_TITLE)
        title = (row.get(title_col) or "")[:120] if title_col else ""
        date_col = _find_column(headers, ALIASES_DATE)
        sold_date = row.get(date_col) if date_col else ""
        details.append({
            "row_index": i + 2,
            "title": title,
            "price_usd": usd,
            "sold_date": sold_date,
            "basis": meta.get("basis", ""),
        })
    return prices, details, skipped


def analyze_sold_csv(
    file_like: TextIO | BinaryIO,
    keyword: str = "",
    marketplace: str = "EBAY_US (manual)",
    exclude_outliers: bool = True,
    encoding: str = "utf-8-sig",
) -> dict:
    """
    CSV を読み analyze_prices と同型の dict を返す。

    data_source は 'sold_csv' 固定。
    """
    if hasattr(file_like, "read") and isinstance(file_like.read(0), bytes) if False else False:
        pass  # type narrow
    raw = file_like.read()
    if isinstance(raw, bytes):
        text = raw.decode(encoding)
    else:
        text = str(raw)

    f = io.StringIO(text)
    reader = csv.DictReader(f)
    headers = reader.fieldnames or []
    if not headers:
        return _empty_result(keyword, marketplace, "CSVにヘッダーがありません")

    rows = list(reader)
    str_rows: list[dict[str, str]] = [
        {k: (v or "") for k, v in r.items()} for r in rows
    ]

    prices, details, skipped = parse_sold_rows(str_rows, list(headers))

    if not prices:
        return _empty_result(
            keyword, marketplace,
            f"有効な金額行がありません（スキップ {skipped} 行）",
        )

    stats, rec = _stats_and_recommendations(prices, exclude_outliers=exclude_outliers)

    kw = keyword or (headers[0] if headers else "sold_import")

    # items: 分析用の擬似リスト（ダッシュボード表用）
    pseudo_items = []
    for d in details[:50]:
        pseudo_items.append({
            "title": d["title"],
            "price_usd": d["price_usd"],
            "currency": "USD",
            "price": d["price_usd"],
            "item_url": "",
            "condition": "SOLD_SAMPLE",
        })

    return {
        "keyword": kw,
        "marketplace": marketplace,
        "total_hits": len(rows),
        "sampled": stats["count"],
        "stats": stats,
        "recommended_sell_usd": rec["recommended_sell_usd"],
        "safe_sell_usd": rec["safe_sell_usd"],
        "aggressive_sell_usd": rec["aggressive_sell_usd"],
        "premium_sell_usd": rec["premium_sell_usd"],
        "items": pseudo_items,
        "data_source": "sold_csv",
        "skipped_rows": skipped,
        "warnings": _warnings(stats["count"], skipped),
        "row_details": details,
    }


def _empty_result(keyword: str, marketplace: str, error: str) -> dict:
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
        "data_source": "sold_csv",
        "skipped_rows": 0,
        "warnings": [error],
        "row_details": [],
    }


def _warnings(n: int, skipped: int) -> list[str]:
    w = []
    if n < 5:
        w.append(f"サンプルが {n} 件のみです。可能なら 5 件以上を蓄積してください。")
    if skipped:
        w.append(f"金額が取れなかった行: {skipped} 行スキップしました。")
    return w


def compare_active_vs_sold(
    active: dict,
    sold: dict,
) -> dict:
    """
    Browse API 結果と落札 CSV 結果を並べて比較用サマリーを返す。
    """
    def g(d: dict, key: str) -> Optional[float]:
        s = d.get("stats")
        if not s:
            return None
        return s.get(key)

    return {
        "active_median": g(active, "median"),
        "sold_median": g(sold, "median"),
        "delta_median_usd": (
            (g(active, "median") or 0) - (g(sold, "median") or 0)
            if g(active, "median") is not None and g(sold, "median") is not None
            else None
        ),
        "interpretation": (
            "落札中央値が現在出品中央値より低い場合、相場下落か、"
            "高値で売れ残っている出品が多い可能性があります。"
            "（逆もあり得ます。サンプル数に注意）"
        ),
    }


TEMPLATE_FIELDNAMES = [
    "title",
    "sold_price_usd",
    "currency",
    "shipping_usd",
    "sold_date",
    "source",
    "notes",
]

TEMPLATE_SAMPLE_ROWS = [
    {
        "title": "Kutani vase Meiji period antique",
        "sold_price_usd": "245.00",
        "currency": "USD",
        "shipping_usd": "35.00",
        "sold_date": "2026-04-01",
        "source": "ebay_sold_search",
        "notes": "例: Sold フィルタで転記",
    },
    {
        "title": "Japanese Kutani porcelain vase",
        "sold_price_usd": "189.99",
        "currency": "USD",
        "shipping_usd": "",
        "sold_date": "2026-04-05",
        "source": "terapeak_memo",
        "notes": "Terapeak の平均帯に合わせたサンプル値",
    },
]


def template_csv_bytes() -> bytes:
    """ダッシュボード用: テンプレのバイト列（UTF-8 BOM）。"""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TEMPLATE_FIELDNAMES)
    w.writeheader()
    w.writerows(TEMPLATE_SAMPLE_ROWS)
    return buf.getvalue().encode("utf-8-sig")


def make_template_csv(path: str = "sold_prices_template.csv") -> str:
    """テンプレート CSV を書き出す。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TEMPLATE_FIELDNAMES)
        w.writeheader()
        w.writerows(TEMPLATE_SAMPLE_ROWS)
    return path


def format_sold_report(a: dict) -> str:
    """テキストレポート"""
    if not a.get("stats"):
        return "\n".join(a.get("warnings") or ["データなし"])
    s = a["stats"]
    lines = [
        "━" * 62,
        "  落札・手動CSV 相場分析",
        "━" * 62,
        f"  行数（ファイル）: {a['total_hits']}",
        f"  分析対象（USD）: {a['sampled']} 件",
        f"  データソース: {a.get('data_source', '')}",
        "",
        f"  【価格分布 USD】",
        f"    最安   ${s['min']:>8.2f}",
        f"    P25    ${s['p25']:>8.2f}",
        f"    中央値 ${s['median']:>8.2f}",
        f"    平均   ${s['mean']:>8.2f}",
        f"    P75    ${s['p75']:>8.2f}",
        f"    最高   ${s['max']:>8.2f}",
        "",
        f"  【推奨販売価格】",
        f"    🎯 バランス: ${a['recommended_sell_usd']:.2f}",
        f"    ⚡ 速売:     ${a['safe_sell_usd']:.2f}",
        f"    💰 標準:     ${a['aggressive_sell_usd']:.2f}",
        f"    👑 強気:     ${a['premium_sell_usd']:.2f}",
        "━" * 62,
    ]
    for w in a.get("warnings") or []:
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)
