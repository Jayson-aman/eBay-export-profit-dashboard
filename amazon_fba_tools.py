"""
amazon_fba_tools.py — 楽天/Yahoo!ショッピング仕入れ → Amazon FBA販売の利益判定。

Amazonの商品価格・手数料は公式APIやセラーセントラルの数値で最終確認する前提。
本モジュールは仕入れ候補を粗くスクリーニングするための保守的な概算ツール。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from amasearch import amazon_co_jp_search_url


DEFAULT_RESTRICTED_KEYWORDS = (
    "医薬品",
    "医薬部外品",
    "サプリ",
    "化粧品",
    "香水",
    "食品",
    "酒",
    "アルコール",
    "電池",
    "バッテリー",
    "リチウム",
    "充電器",
    "アダプタ",
    "互換",
    "ブランド",
    "正規品",
    "キャラクター",
)

DEFAULT_PREMIUM_KEYWORDS = (
    "限定",
    "数量限定",
    "初回限定",
    "廃盤",
    "生産終了",
    "終売",
    "完売",
    "希少",
    "レア",
    "復刻",
    "コラボ",
    "別注",
    "特装版",
    "プレミアム",
    "高級",
    "日本製",
    "Made in Japan",
    "made in japan",
    "職人",
    "伝統工芸",
    "有田焼",
    "九谷焼",
    "波佐見焼",
    "南部鉄器",
    "燕三条",
    # 購入制限・抽選・チャネル限定（転売候補の手がかり。規約・出品制限は別途確認）
    "お一人様",
    "おひとり様",
    "お一人さま",
    "1名様",
    "一名様",
    "一人様",
    "お一人様1点",
    "お一人様1点限り",
    "お一人様1点まで",
    "1名様1点",
    "1名様1点まで",
    "1人1点",
    "一人1点",
    "1点限り",
    "1点のみ",
    "1点まで",
    "購入制限",
    "購入数量制限",
    "販売制限",
    "数量制限",
    "個数制限",
    "抽選",
    "抽選販売",
    "抽選当選",
    "先行販売",
    "先行予約",
    "先行発売",
    "予約販売",
    "予約限定",
    "受注生産",
    "会員限定",
    "公式限定",
    "店舗限定",
    "オンライン限定",
    "Web限定",
    "完売御礼",
    "再入荷なし",
    "再販なし",
    "ロット限定",
    "シリアル",
    "シリアルナンバー",
    "ナンバー入り",
)

DEFAULT_COMMODITY_KEYWORDS = (
    "互換",
    "汎用",
    "ノーブランド",
    "大量",
    "まとめ売り",
    "訳あり",
    "アウトレット",
    "最安",
)


@dataclass(frozen=True)
class AmazonFbaConfig:
    """Amazon FBA販売の概算条件。"""

    amazon_price_jpy: int
    referral_fee_rate: float = 0.10
    fba_fee_jpy: int = 600
    inbound_shipping_jpy: int = 120
    prep_cost_jpy: int = 80
    other_cost_jpy: int = 0
    return_allowance_rate: float = 0.02
    target_margin_pct: float = 20.0
    min_review_count: int = 5
    min_review_avg: float = 3.5
    use_points_as_discount: bool = True
    premium_only: bool = False
    min_premium_score: float = 45.0
    min_sell_through_score: float = 55.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def effective_source_cost_jpy(
    item: dict[str, Any],
    *,
    use_points_as_discount: bool = True,
) -> int:
    """ポイント還元を実質値引きとして扱った仕入れ価格を返す。"""

    cost = _to_int(item.get("cost_jpy"))
    point_rate = max(_to_int(item.get("point_rate"), 0), 0)
    if not use_points_as_discount:
        return cost
    return max(math.ceil(cost * (1 - point_rate / 100)), 0)


def estimate_popularity_score(item: dict[str, Any]) -> float:
    """
    モール内のレビュー情報から人気度を0〜100程度で推定。

    公式の販売数ではないため、レビュー数・評価・ポイント還元・在庫情報の合成スコアに留める。
    """

    review_count = max(_to_int(item.get("review_count")), 0)
    review_avg = max(min(_to_float(item.get("review_avg")), 5.0), 0.0)
    point_rate = max(_to_int(item.get("point_rate"), 0), 0)
    has_stock = bool(item.get("availability") == 1 or item.get("in_stock") is True)

    review_volume = min(math.log1p(review_count) / math.log(501), 1.0) * 55
    review_quality = (review_avg / 5.0) * 30
    point_bonus = min(point_rate, 20) / 20 * 10
    stock_bonus = 5 if has_stock else 0
    return round(review_volume + review_quality + point_bonus + stock_bonus, 1)


def restriction_flags(product_name: str) -> list[str]:
    """Amazon出品制限や真贋確認のリスクが高い語を簡易検出する。"""

    name = product_name or ""
    return [kw for kw in DEFAULT_RESTRICTED_KEYWORDS if kw in name]


def premium_flags(product_name: str) -> list[str]:
    """プレミアム価値の手がかりになる語を検出する。"""

    name = product_name or ""
    return [kw for kw in DEFAULT_PREMIUM_KEYWORDS if kw in name]


def commodity_flags(product_name: str) -> list[str]:
    """価格競争や売れ残りにつながりやすい汎用品の語を検出する。"""

    name = product_name or ""
    return [kw for kw in DEFAULT_COMMODITY_KEYWORDS if kw in name]


def estimate_premium_score(item: dict[str, Any]) -> float:
    """商品名・レビュー・価格帯からプレミアム価値を0〜100で概算する。"""

    name = str(item.get("product_name", ""))
    cost = _to_int(item.get("cost_jpy"))
    review_avg = max(min(_to_float(item.get("review_avg")), 5.0), 0.0)
    premiums = premium_flags(name)
    commodities = commodity_flags(name)

    keyword_score = min(len(premiums) * 18, 54)
    quality_score = (review_avg / 5.0) * 18
    price_score = min(math.log1p(max(cost, 0)) / math.log(30001), 1.0) * 18
    commodity_penalty = min(len(commodities) * 12, 30)
    return round(max(keyword_score + quality_score + price_score - commodity_penalty, 0), 1)


def estimate_sell_through_score(item: dict[str, Any]) -> float:
    """
    売れ残りにくさを0〜100で概算する。

    実販売数ではないため、レビュー量・評価・在庫・プレミアム性・汎用品リスクを合成する。
    """

    popularity = estimate_popularity_score(item)
    premium = estimate_premium_score(item)
    name = str(item.get("product_name", ""))
    restricted = restriction_flags(name)
    commodities = commodity_flags(name)

    score = popularity * 0.65 + premium * 0.35
    score -= min(len(restricted) * 8, 24)
    score -= min(len(commodities) * 8, 24)
    return round(max(min(score, 100), 0), 1)


def inventory_risk_label(sell_through_score: float, premium_score: float) -> str:
    """売れ残りリスクの表示ラベル。"""

    if sell_through_score >= 70 and premium_score >= 45:
        return "低"
    if sell_through_score >= 50:
        return "中"
    return "高"


def buy_timing_verdict(
    *,
    judge: str,
    margin_pct: float,
    inventory_risk: str,
    profit_jpy: int,
    sell_through_score: float,
    target_margin_pct: float,
    restriction_flags: str,
    commodity_flags: str,
) -> tuple[str, str]:
    """
    入力したAmazon想定価格・国内モールの候補に基づく「買い時」の目安。

    Amazonの実勢・Keepaの販売速度は含まないため、最終判断は別途確認する前提。
    """

    restrict_txt = (restriction_flags or "").strip()
    commodity_txt = (commodity_flags or "").strip()
    extras: list[str] = []
    if commodity_txt:
        extras.append("汎用品・まとめ売り等のキーワードがあり価格競争に注意。")

    if profit_jpy <= 0:
        return (
            "見送り",
            "想定Amazon販売価格では利益が出ないかゼロです。仕入れ・想定売価・手数料を見直してください。",
        )

    if judge == "STOP":
        return (
            "見送り",
            "総合判定はSTOPです。赤字または目標利益率未達の可能性が高いです。",
        )

    if restrict_txt:
        extras.append(
            "商品名に規制・真贋確認の手がかり語が含まれる場合があります。Amazonの出品可否を確認してください。"
        )

    if judge == "HOLD":
        msg = (
            f"利益は出ていますが目標利益率{target_margin_pct:.0f}%や売れやすさ条件を満たしていない可能性があります。"
            f"現在の利幅は約{margin_pct:.1f}%です。"
        )
        return "様子見", msg + (" " + " ".join(extras) if extras else "")

    if judge == "CHECK":
        return (
            "様子見",
            "利幅は目標付近ですが、レビュー不足・売れやすさ不足・リスク語のいずれかがあります。"
            " Keepaで販売速度を確認してください。"
            + (" " + " ".join(extras) if extras else ""),
        )

    if (
        inventory_risk == "低"
        and sell_through_score >= 65
        and margin_pct >= target_margin_pct + 5
    ):
        return (
            "買い時",
            "利益・モール内人気・売れ残りリスクのバランスが良いです。"
            " Amazonのカート価格とKeepaの推移で最終確認後、数量は少額からが安全です。"
            + (" " + " ".join(extras) if extras else ""),
        )

    if inventory_risk == "低":
        return (
            "買い時寄り",
            "条件は良好です。Amazonの同一JAN・販売数・カート価格を確認してから仕入れ判断してください。"
            + (" " + " ".join(extras) if extras else ""),
        )

    return (
        "様子見",
        "判定はGOですが売れ残りリスクは中〜高めの目安です。販売速度・在庫リスクを確認してください。"
        + (" " + " ".join(extras) if extras else ""),
    )


def calc_amazon_fba_profit(
    item: dict[str, Any],
    config: AmazonFbaConfig,
) -> dict[str, Any]:
    """1商品についてAmazon FBA販売時の利益・利益率を概算する。"""

    amazon_price = max(_to_int(config.amazon_price_jpy), 0)
    source_cost = _to_int(item.get("cost_jpy"))
    effective_cost = effective_source_cost_jpy(
        item,
        use_points_as_discount=config.use_points_as_discount,
    )
    referral_fee = round(amazon_price * config.referral_fee_rate)
    return_allowance = round(amazon_price * config.return_allowance_rate)
    total_cost = (
        effective_cost
        + referral_fee
        + config.fba_fee_jpy
        + config.inbound_shipping_jpy
        + config.prep_cost_jpy
        + config.other_cost_jpy
        + return_allowance
    )
    profit = amazon_price - total_cost
    margin_pct = (profit / amazon_price * 100) if amazon_price else 0.0
    roi_pct = (profit / total_cost * 100) if total_cost > 0 else 0.0

    review_count = _to_int(item.get("review_count"))
    review_avg = _to_float(item.get("review_avg"))
    popularity_score = estimate_popularity_score(item)
    premium_score = estimate_premium_score(item)
    sell_through_score = estimate_sell_through_score(item)
    flags = restriction_flags(str(item.get("product_name", "")))
    premiums = premium_flags(str(item.get("product_name", "")))
    commodities = commodity_flags(str(item.get("product_name", "")))
    is_popular_enough = (
        review_count >= config.min_review_count
        and review_avg >= config.min_review_avg
    )
    meets_margin = margin_pct >= config.target_margin_pct
    meets_premium = premium_score >= config.min_premium_score
    meets_sell_through = sell_through_score >= config.min_sell_through_score

    if (
        meets_margin
        and is_popular_enough
        and meets_sell_through
        and (meets_premium or not config.premium_only)
        and not flags
    ):
        judge = "GO"
    elif profit > 0 and meets_margin:
        judge = "CHECK"
    elif profit > 0:
        judge = "HOLD"
    else:
        judge = "STOP"

    inv_risk = inventory_risk_label(sell_through_score, premium_score)
    buy_timing, buy_timing_note = buy_timing_verdict(
        judge=judge,
        margin_pct=round(margin_pct, 1),
        inventory_risk=inv_risk,
        profit_jpy=int(profit),
        sell_through_score=sell_through_score,
        target_margin_pct=config.target_margin_pct,
        restriction_flags=", ".join(flags),
        commodity_flags=", ".join(commodities),
    )

    return {
        **item,
        "amazon_price_jpy": amazon_price,
        "source_cost_jpy": source_cost,
        "effective_cost_jpy": effective_cost,
        "referral_fee_jpy": referral_fee,
        "fba_fee_jpy": config.fba_fee_jpy,
        "inbound_shipping_jpy": config.inbound_shipping_jpy,
        "prep_cost_jpy": config.prep_cost_jpy,
        "other_cost_jpy": config.other_cost_jpy,
        "return_allowance_jpy": return_allowance,
        "total_cost_jpy": total_cost,
        "profit_jpy": profit,
        "margin_pct": round(margin_pct, 1),
        "roi_pct": round(roi_pct, 1),
        "popularity_score": popularity_score,
        "premium_score": premium_score,
        "sell_through_score": sell_through_score,
        "inventory_risk": inv_risk,
        "premium_flags": ", ".join(premiums),
        "commodity_flags": ", ".join(commodities),
        "restriction_flags": ", ".join(flags),
        "judge": judge,
        "buy_timing": buy_timing,
        "buy_timing_note": buy_timing_note,
        "amazon_search_url": amazon_co_jp_search_url(str(item.get("product_name", ""))),
    }


def rank_amazon_fba_candidates(
    items: list[dict[str, Any]],
    config: AmazonFbaConfig,
) -> list[dict[str, Any]]:
    """検索結果をAmazon FBA利益見込み順に並べる。"""

    rows = [calc_amazon_fba_profit(item, config) for item in items]
    _timing_rank = {"買い時": 4, "買い時寄り": 3, "様子見": 2, "見送り": 1}

    rows.sort(
        key=lambda r: (
            _timing_rank.get(r.get("buy_timing", ""), 0),
            r["judge"] == "GO",
            r["inventory_risk"] == "低",
            r["premium_score"],
            r["sell_through_score"],
            r["margin_pct"],
            r["profit_jpy"],
        ),
        reverse=True,
    )
    return rows


def summarize_ranked_candidates(rows: list[dict[str, Any]]) -> dict[str, int]:
    """判定件数のサマリー。"""

    return {
        "total": len(rows),
        "go": sum(1 for r in rows if r.get("judge") == "GO"),
        "check": sum(1 for r in rows if r.get("judge") == "CHECK"),
        "hold": sum(1 for r in rows if r.get("judge") == "HOLD"),
        "stop": sum(1 for r in rows if r.get("judge") == "STOP"),
    }
