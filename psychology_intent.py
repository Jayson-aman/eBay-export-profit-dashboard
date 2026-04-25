"""
psychology_intent.py — 購買意欲のヒューリスティクス（先読み・季節・心理ドライバー）

※ 個人の内面を断定するものではなく、小売・ECで用いる
  「需要の季節性・行事・心理トリガー」の簡易モデルです。
  実売上を保証しません。パラメータは運用で調整してください。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

# profit_tools のカテゴリにデフォルトで付与する心理タグ（拡張カタログで上書き可）
DEFAULT_CATEGORY_PSYCH_TAGS: dict[str, list[str]] = {
    "骨董品・浮世絵": ["nostalgia", "collection", "gift_elite"],
    "骨董品・陶磁器": ["nostalgia", "collection", "gift_elite"],
    "骨董品・茶道具": ["nostalgia", "ritual", "gift_elite"],
    "骨董品・漆器・蒔絵": ["nostalgia", "gift_elite", "status_display"],
    "骨董品・仏像・仏具": ["spiritual", "collection", "nostalgia"],
    "骨董品・着物・帯": ["nostalgia", "status_display", "gift_elite"],
    "骨董品・古銭・切手": ["collection", "investment_proxy", "nostalgia"],
    "骨董品・古書": ["nostalgia", "collection", "gift_casual"],
    "骨董品・刀剣": ["collection", "status_display", "novelty"],
    "カメラ・レンズ": ["novelty", "hobby_deep", "status_display"],
    "時計": ["status_display", "gift_elite", "investment_proxy"],
    "楽器": ["hobby_deep", "self_reward", "nostalgia"],
    "ホビー・フィギュア": ["novelty", "fandom", "gift_casual"],
    "ホビー・ガンプラ": ["novelty", "fandom", "hobby_deep"],
    "ホビー・ポケモンカード": ["collection", "investment_proxy", "nostalgia"],
    "ゲーム": ["novelty", "nostalgia", "escape"],
    "ファッション": ["status_display", "gift_casual", "self_reward"],
    "包丁・キッチン": ["comfort_home", "gift_elite", "self_reward"],
    "化粧品": ["self_reward", "gift_casual", "comfort_home"],
    "建材・DIY・補修材": ["comfort_home", "self_reward", "novelty"],
    "防水・シーリング・塗料": ["comfort_home", "self_reward", "novelty"],
}

# 心理ドライバー: 需要に効く方向（係数の素）と説明
PSYCH_DRIVERS: dict[str, dict[str, Any]] = {
    "nostalgia": {"label": "ノスタルジア・希少性", "base": 0.04},
    "collection": {"label": "コレクション欲", "base": 0.035},
    "gift_elite": {"label": "高級ギフト需要", "base": 0.03},
    "gift_casual": {"label": "カジュアルギフト", "base": 0.04},
    "novelty": {"label": "新奇・話題性", "base": 0.045},
    "fandom": {"label": "ファン・コミュニティ", "base": 0.04},
    "status_display": {"label": "ステータス・見せる消費", "base": 0.03},
    "comfort_home": {"label": "居場所・安心（巣ごもり）", "base": 0.025},
    "self_reward": {"label": "自分へのご褒美", "base": 0.03},
    "escape": {"label": "逃避・ストレス緩和（趣味）", "base": 0.025},
    "ritual": {"label": "儀式・趣味的没入", "base": 0.02},
    "spiritual": {"label": "精神性・祈り", "base": 0.02},
    "hobby_deep": {"label": "ハマり・マニア層", "base": 0.03},
    "investment_proxy": {"label": "価値保存の期待", "base": 0.02},
}

# 行事・季節の係数（月 → 乗数に寄与する重み）
SEASONAL_MONTH_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"gift_casual": 0.5, "gift_elite": 0.3, "self_reward": 0.4},
    2: {"gift_casual": 0.9, "gift_elite": 0.7, "nostalgia": 0.2},
    3: {"novelty": 0.3, "fandom": 0.2},
    4: {"novelty": 0.25, "gift_casual": 0.2},
    5: {"gift_casual": 0.5, "gift_elite": 0.3},
    6: {"self_reward": 0.4, "gift_casual": 0.2},
    7: {"escape": 0.25, "novelty": 0.2},
    8: {"escape": 0.2},
    9: {"self_reward": 0.4, "gift_casual": 0.3},
    10: {"gift_elite": 0.3, "collection": 0.25},
    11: {"gift_elite": 0.9, "gift_casual": 0.85, "gift": 0.9},
    12: {"gift_elite": 1.0, "gift_casual": 1.0, "nostalgia": 0.35},
}

# 曜日（購買意欲の微調整）: 週末の閲覧 → 月曜の購入 などの粗い近似
WEEKDAY_FACTOR: dict[int, float] = {
    0: 1.02,  # Mon
    1: 1.0,
    2: 0.99,
    3: 0.99,
    4: 1.01,
    5: 1.03,  # Fri
    6: 1.04,  # Sat browse
}

# 仕向け先の文化・イベントのざっくり補正
REGION_EVENT_BOOST: dict[str, dict[str, float]] = {
    "アメリカ": {"gift_elite": 0.06, "gift_casual": 0.05, "novelty": 0.04},
    "イギリス": {"gift_elite": 0.05, "nostalgia": 0.04},
    "カナダ": {"gift_casual": 0.5, "gift_elite": 0.3},
    "ドイツ": {"gift_elite": 0.06, "nostalgia": 0.03},
    "オーストラリア": {"escape": 0.25, "novelty": 0.2},
}


def _default_catalog_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config", "product_catalog.json")


def load_extension_catalog(path: Optional[str] = None) -> dict[str, Any]:
    """config/product_catalog.json の categories を読み込む（無ければ空）。"""
    p = path or _default_catalog_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("categories") or {}
    except (json.JSONDecodeError, OSError):
        return {}


def merged_category_psych_tags(
    category: str,
    extension: Optional[dict[str, Any]] = None,
) -> list[str]:
    """カテゴリ名に対応する psych_tags（拡張カタログ優先）。"""
    ext = extension if extension is not None else load_extension_catalog()
    if category in ext and isinstance(ext[category], dict):
        tags = ext[category].get("psych_tags")
        if isinstance(tags, list) and tags:
            return [str(t) for t in tags]
    return list(DEFAULT_CATEGORY_PSYCH_TAGS.get(category, ["novelty", "gift_casual"]))


def destination_boost_for(category: str, destination: str, extension: dict) -> float:
    """拡張カタログの destination_weight に基づく 0.9〜1.15 程度の補正。"""
    meta = extension.get(category)
    if not isinstance(meta, dict):
        return 1.0
    dw = meta.get("destination_weight") or meta.get("destination")
    if not isinstance(dw, dict):
        return 1.0
    return float(dw.get(destination, dw.get("__default__", 1.0)))


def forward_horizon_months(
    anchor: date,
    months: int,
    seasonal_peaks: list[int],
) -> str:
    """今後 months ヶ月のうち、ピーク月が含まれるか先読みメモ。"""
    peaks = set(seasonal_peaks)
    hit: list[int] = []
    for i in range(1, months + 1):
        m = (anchor.month - 1 + i) % 12 + 1
        if m in peaks:
            hit.append(m)
    if not hit:
        return f"今後{months}ヶ月の暦上、登録ピーク月（{sorted(peaks)}）とは重ならない見込みです。"
    return f"今後{months}ヶ月の暦上で需要ピーク月 {sorted(set(hit))} 月と重なります（季節要因の目安）。"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_purchase_intent(
    category: str,
    destination: str = "アメリカ",
    when: Optional[date] = None,
    *,
    social_mood: float = 0.0,
    extension_catalog: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    購買意欲スコア（0〜100）と、判断用メモを返す。

    social_mood:
      -1.0 不安・節約寄り 〜 +1.0 浪費・ご褒美寄り（ニュースや自己体感のスライダー用）
    """
    when = when or date.today()
    ext = extension_catalog if extension_catalog is not None else load_extension_catalog()
    tags = merged_category_psych_tags(category, ext)

    # 拡張の seasonal_peaks
    peaks: list[int] = []
    meta = ext.get(category)
    if isinstance(meta, dict) and isinstance(meta.get("seasonal_peaks"), list):
        peaks = [int(x) for x in meta["seasonal_peaks"]]

    acc = 0.0
    factor_rows: list[dict[str, Any]] = []
    month = when.month
    wd = WEEKDAY_FACTOR.get(when.weekday(), 1.0)

    for tag in tags:
        drv = PSYCH_DRIVERS.get(tag)
        if not drv:
            continue
        base = float(drv["base"])
        season_w = 1.0
        for mkey, w in SEASONAL_MONTH_WEIGHTS.get(month, {}).items():
            if mkey in tag or (mkey == "gift" and "gift" in tag):
                season_w += w * 0.15
        reg = REGION_EVENT_BOOST.get(destination, {})
        reg_b = 0.0
        for k, v in reg.items():
            if k in tag:
                reg_b += v
        contrib_raw = base * season_w + reg_b
        contrib = contrib_raw * wd
        acc += contrib
        factor_rows.append({
            "tag": tag,
            "label": drv["label"],
            "contribution": round(contrib, 4),
            "note": f"月{month}・{destination}・曜日×{wd:.2f}",
        })

    dest_mult = destination_boost_for(category, destination, ext)
    acc *= dest_mult

    # 社会ムード: 不安が高いと「ギフト」より「小さなご褒美・コレクション」が相対的に残る
    mood_adj = 0.0
    if social_mood < -0.3:
        mood_adj = -0.02 * abs(social_mood)
        if any("gift_elite" in t for t in tags):
            mood_adj -= 0.015
        if any(t in ("collection", "nostalgia", "escape") for t in tags):
            mood_adj += 0.02 * abs(social_mood)
    elif social_mood > 0.3:
        mood_adj = 0.025 * social_mood
        if any("gift" in t for t in tags):
            mood_adj += 0.01

    acc += mood_adj

    # 0〜100 スコア
    raw_score = 50 + acc * 180
    intent_score = _clamp(raw_score, 0.0, 100.0)
    intent_multiplier = _clamp(0.92 + (intent_score - 50) * 0.004, 0.88, 1.12)

    horizon = ""
    if peaks:
        horizon = forward_horizon_months(when, 3, peaks)
    else:
        # タグから推定ピーク（ギフト系）
        default_peaks = [11, 12, 2]
        if any("gift" in t for t in tags):
            horizon = forward_horizon_months(when, 3, default_peaks)
        else:
            horizon = "季節ピークは拡張カタログ（seasonal_peaks）で登録してください。"

    from climate_season import analyze_climate_context

    climate_ctx = analyze_climate_context(destination, when, category)
    # 気候×季節の相性を軽くブレンド（過信しないよう弱い指数）
    cf = float(climate_ctx.get("category_fit_multiplier") or 1.0)
    blended = _clamp(intent_multiplier * (cf ** 0.35), 0.85, 1.18)

    return {
        "category": category,
        "destination": destination,
        "as_of": when.isoformat(),
        "psych_tags": tags,
        "intent_score": round(intent_score, 1),
        "intent_multiplier": round(intent_multiplier, 4),
        "intent_multiplier_climate_blended": round(blended, 4),
        "factors": factor_rows,
        "social_mood_applied": social_mood,
        "mood_adjustment": round(mood_adj, 4),
        "destination_multiplier": round(dest_mult, 4),
        "forward_horizon_note": horizon,
        "climate_context": climate_ctx,
        "disclaimer": (
            "ヒューリスティクスであり、実際の購買心理・売上を保証するものではありません。"
        ),
    }


def format_intent_report(p: dict[str, Any]) -> str:
    from climate_season import format_climate_report

    lines = [
        "━" * 62,
        "  購買意欲・先読み（ヒューリスティクス）",
        "━" * 62,
        f"  カテゴリ: {p['category']}  →  {p['destination']}",
        f"  基準日: {p['as_of']}",
        f"  意欲スコア: {p['intent_score']}/100",
        f"  需要補正係数（参考）: ×{p['intent_multiplier']}",
        f"  気候ブレンド後（参考）: ×{p.get('intent_multiplier_climate_blended', p['intent_multiplier'])}",
        f"  仕向け補正: ×{p['destination_multiplier']}",
        "",
        "  【心理タグ】 " + ", ".join(p["psych_tags"]),
        "",
        "  【先読み（3ヶ月）】",
        "  " + p["forward_horizon_note"],
        "",
        p["disclaimer"],
        "━" * 62,
    ]
    cc = p.get("climate_context")
    if cc:
        lines.append(format_climate_report(cc))
    return "\n".join(lines)


@dataclass
class CatalogMerge:
    """UI 用: 利益率表示とカテゴリ一覧のマージ結果。"""
    categories_display: dict[str, str] = field(default_factory=dict)
    extension_keys: list[str] = field(default_factory=list)


def merge_categories_for_ui(
    base_categories: dict[str, str],
    extension: Optional[dict[str, Any]] = None,
) -> CatalogMerge:
    """profit_tools.CATEGORIES と JSON の margin_hint をマージ。"""
    ext = extension if extension is not None else load_extension_catalog()
    out = dict(base_categories)
    extra_keys: list[str] = []
    for k, v in ext.items():
        if not isinstance(v, dict):
            continue
        hint = v.get("margin_hint") or v.get("typical_margin")
        if isinstance(hint, str) and hint:
            out[k] = hint
            if k not in base_categories:
                extra_keys.append(k)
    return CatalogMerge(categories_display=out, extension_keys=sorted(extra_keys))
