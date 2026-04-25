"""
climate_season.py — 仕向け国の半球・気候帯・現地の春夏秋冬に応じた需要ヒント

※ 気象の個別予報ではなく、販売計画用の粗いヒューリスティクスです。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


# 仕向け先（profit_tools.DESTINATION_ZONE と同じ表記を優先）
# hemisphere: north / south / equatorial（赤道付近は雨季乾季より「通年暑」寄りで扱う）
# climate: cold / cool / temperate / warm / hot / tropical / desert / mediterranean
REGION_PROFILE: dict[str, dict[str, str]] = {
    "アメリカ": {"hemisphere": "north", "climate": "temperate"},
    "US": {"hemisphere": "north", "climate": "temperate"},
    "USA": {"hemisphere": "north", "climate": "temperate"},
    "カナダ": {"hemisphere": "north", "climate": "cold"},
    "メキシコ": {"hemisphere": "north", "climate": "warm"},
    "イギリス": {"hemisphere": "north", "climate": "cool"},
    "UK": {"hemisphere": "north", "climate": "cool"},
    "GB": {"hemisphere": "north", "climate": "cool"},
    "ドイツ": {"hemisphere": "north", "climate": "cool"},
    "DE": {"hemisphere": "north", "climate": "cool"},
    "フランス": {"hemisphere": "north", "climate": "temperate"},
    "FR": {"hemisphere": "north", "climate": "temperate"},
    "イタリア": {"hemisphere": "north", "climate": "mediterranean"},
    "IT": {"hemisphere": "north", "climate": "mediterranean"},
    "スペイン": {"hemisphere": "north", "climate": "mediterranean"},
    "ES": {"hemisphere": "north", "climate": "mediterranean"},
    "オランダ": {"hemisphere": "north", "climate": "cool"},
    "ベルギー": {"hemisphere": "north", "climate": "cool"},
    "スイス": {"hemisphere": "north", "climate": "cold"},
    "スウェーデン": {"hemisphere": "north", "climate": "cold"},
    "EU": {"hemisphere": "north", "climate": "temperate"},
    "オーストラリア": {"hemisphere": "south", "climate": "warm"},
    "AU": {"hemisphere": "south", "climate": "warm"},
    "ニュージーランド": {"hemisphere": "south", "climate": "cool"},
    "NZ": {"hemisphere": "south", "climate": "cool"},
    "ブラジル": {"hemisphere": "south", "climate": "tropical"},
    "BR": {"hemisphere": "south", "climate": "tropical"},
    "アルゼンチン": {"hemisphere": "south", "climate": "temperate"},
    "チリ": {"hemisphere": "south", "climate": "mediterranean"},
    "南アフリカ": {"hemisphere": "south", "climate": "temperate"},
    "中国": {"hemisphere": "north", "climate": "temperate"},
    "韓国": {"hemisphere": "north", "climate": "temperate"},
    "台湾": {"hemisphere": "north", "climate": "subtropical"},
    "タイ": {"hemisphere": "north", "climate": "tropical"},
    "ベトナム": {"hemisphere": "north", "climate": "tropical"},
    "マレーシア": {"hemisphere": "north", "climate": "tropical"},
    "シンガポール": {"hemisphere": "north", "climate": "tropical"},
    "フィリピン": {"hemisphere": "north", "climate": "tropical"},
    "インドネシア": {"hemisphere": "equatorial", "climate": "tropical"},
    "UAE": {"hemisphere": "north", "climate": "desert"},
    "サウジアラビア": {"hemisphere": "north", "climate": "desert"},
    "エジプト": {"hemisphere": "north", "climate": "desert"},
}

DEFAULT_PROFILE = {"hemisphere": "north", "climate": "temperate"}

SEASON_JA = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
}

CLIMATE_JA = {
    "cold": "寒冷（冬が厳しい）",
    "cool": "冷涼",
    "temperate": "温帯（四季）",
    "warm": "温暖",
    "hot": "高温・暑熱",
    "tropical": "熱帯（高温多湿）",
    "desert": "砂漠・乾燥・酷暑",
    "mediterranean": "地中海性（夏乾燥・冬雨）",
    "subtropical": "亜熱帯",
}


def _season_from_month_north(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _season_from_month_south(month: int) -> str:
    """南半球の暦上・季節（欧米式の春夏秋冬）。"""
    if month in (9, 10, 11):
        return "spring"
    if month in (12, 1, 2):
        return "summer"
    if month in (3, 4, 5):
        return "autumn"
    return "winter"


def _season_equatorial(month: int) -> str:
    """赤道付近は雨季乾季の代わりに「通年」を崩して便宜上の季を返す。"""
    # 6-10 乾季寄り / 11-5 雨季寄り（東南アジアのざっくり）
    if month in (11, 12, 1, 2, 3, 4, 5):
        return "wet_season"
    return "dry_season"


TROPICAL_WET_DRY = frozenset({
    "タイ", "ベトナム", "マレーシア", "シンガポール", "フィリピン", "インドネシア",
})


def local_season_key(when: date, destination: str) -> str:
    prof = REGION_PROFILE.get(destination, DEFAULT_PROFILE)
    h = prof.get("hemisphere", "north")
    c = prof.get("climate", "temperate")
    # 東南アジア等：雨季・乾季の方が生活ニーズと相性が取りやすい
    if destination in TROPICAL_WET_DRY or h == "equatorial":
        return _season_equatorial(when.month)
    if h == "south":
        return _season_from_month_south(when.month)
    return _season_from_month_north(when.month)


def local_season_label(when: date, destination: str) -> str:
    k = local_season_key(when, destination)
    if k == "wet_season":
        return "雨季（高温多湿・除湿・防水ニーズ）"
    if k == "dry_season":
        return "乾季（旅行・アウトドア・冷感ニーズ）"
    return SEASON_JA.get(k, k)


def climate_label(destination: str) -> str:
    prof = REGION_PROFILE.get(destination, DEFAULT_PROFILE)
    c = prof.get("climate", "temperate")
    return CLIMATE_JA.get(c, c)


def _need_lines(season_key: str, climate: str) -> list[str]:
    """季節×気候で「今そこで増えやすいニーズ」（輸出の観点）。"""
    lines: list[str] = []

    if climate in ("cold", "cool"):
        if season_key == "winter":
            lines.append(
                "防寒・室内快適（暖房・加湿器・ホットドリンク文化）＋冬ギフト需要が相対的に上がりやすい。"
            )
        elif season_key == "summer":
            lines.append(
                "冷涼地域でも夏季はレジャー・アウトドア・バケーション需要のピークになりやすい。"
            )
    if climate in ("hot", "tropical", "desert", "subtropical", "warm"):
        if season_key == "summer":
            lines.append(
                "冷感・水分・UV・通気性衣類・省エネ冷却。熱中症対策商材の関心が強まりやすい。"
            )
        elif season_key == "winter":
            lines.append(
                "「冬」でも温暖な地域は衣替えは小さめ。乾燥・暖房による肌・喉へのケア需要に注目。"
            )
    if climate == "desert":
        lines.append(
            "乾燥・砂埃・日射が通年テーマ：スキンケア・目・喉・静電気対策が継続的に意識されやすい。"
        )
    if climate == "mediterranean":
        if season_key == "summer":
            lines.append(
                "夏の乾燥・熱：屋外より室内快適・夜の社交に合う商材・軽食文化に合わせた訴求。"
            )
        elif season_key == "winter":
            lines.append("冬雨が増える地域：屋内趣味・ギフト・ホリデー（国・宗教により異なる）。")

    if season_key == "spring":
        lines.append(
            "新生活・花粉・衣替え・キャンプ／登山シーズン開始：軽量ギア・防花粉・整理収納系を確認。"
        )
    if season_key == "autumn":
        lines.append(
            "学び直し・冬支度・ハロウィン〜年末ギフト準備：ホビー・ギフト・インテリアを確認。"
        )
    if season_key == "summer":
        lines.append(
            "現地が夏ならアウトドア・旅行・サマーイベント・暑中見舞い的ギフト需要を確認。"
        )
    if season_key == "winter":
        lines.append(
            "現地が冬なら巣ごもり・インドア趣味・ホリデー集中（国により11〜12月／1月がピーク）。"
        )

    if not lines:
        lines.append(
            "温帯の四季：春秋は衣替え・花粉・新学期・キャンプ／登山の需要が動きやすい。"
        )

    return lines


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def category_season_fit(
    category: str,
    season_key: str,
    climate: str,
) -> tuple[float, str]:
    """
    カテゴリが「今の季節×気候」とどれだけ相性が良いか 0.5〜1.2 の係数と一言。
    """
    c = category
    score = 1.0
    note = "標準"

    if "骨董" in c or "陶磁器" in c or "茶道具" in c or "漆器" in c:
        score = 1.05
        if season_key == "winter":
            score = 1.08
            note = "冬は室内・ギフト・コレクション需要が出やすい傾向"
        elif season_key == "summer":
            note = "夏は展示会・旅行土産需要も要チェック"

    if "キャンプ" in c or "アウトドア" in c:
        score = 1.12 if season_key in ("spring", "summer", "autumn") else 0.92
        if climate in ("cold", "cool") and season_key == "winter":
            score = 0.88
            note = "厳冬はアウトドア需要が落ちやすい（寒冷地）"
        else:
            note = "温暖〜春秋はアウトドア需要が伸びやすい"

    if "化粧品" in c or "ファッション" in c:
        if climate in ("hot", "tropical", "desert") and season_key in ("summer", "dry_season"):
            score = 1.1
            note = "暑熱・乾燥でスキンケア・軽衣料需要"
        elif climate in ("cold", "cool") and season_key == "winter":
            score = 1.08
            note = "乾燥・防寒ケア需要"

    if "ゲーム" in c or "ホビー" in c or "フィギュア" in c:
        if season_key == "winter":
            score = 1.06
            note = "冬季はインドア趣味が相対的に強い傾向"
        if climate in ("hot", "tropical", "desert") and season_key in ("summer", "dry_season"):
            score = 1.04
            note = "暑熱時は屋内レジャー関心が出やすい"

    if "包丁" in c or "キッチン" in c:
        score = 1.05
        note = "通年だが年末年始・新生活でギフト需要"

    if "建材" in c or "防水" in c or "シーリング" in c or "塗料" in c:
        if season_key in ("spring", "summer", "autumn"):
            score = max(score, 1.06)
            note = "雨漏り・リフォーム・外壁シーズンで補修需要が出やすい"
        if climate in ("hot", "tropical", "wet_season"):
            score = max(score, 1.05)
            note = (note + " / 高温多湿・雨季は防水・カビ対策関心が強まりやすい")

    return round(_clamp(score, 0.5, 1.2), 3), note


def analyze_climate_context(
    destination: str,
    when: Optional[date] = None,
    category: str = "",
) -> dict[str, Any]:
    """ダッシュボード・購買心理から呼び出す統合コンテキスト。"""
    when = when or date.today()
    prof = REGION_PROFILE.get(destination, DEFAULT_PROFILE)
    hem = prof.get("hemisphere", "north")
    climate = prof.get("climate", "temperate")

    sk = local_season_key(when, destination)
    sl = local_season_label(when, destination)

    if sk == "wet_season":
        needs = [
            "雨季：除湿・防カビ・防水・靴・傘・屋内快適グッズの関心が上がりやすい。",
            "通年暑い地域では冷感・虫対策も絡めて検討。",
        ]
    elif sk == "dry_season":
        needs = [
            "乾季：旅行・アウトドア・洗濯物が乾きやすい季節のライフスタイル需要。",
            "熱帯では冷房・熱中症対策のピークになりやすい。",
        ]
    else:
        needs = _need_lines(sk, climate)

    cat_fit = 1.0
    cat_note = ""
    if category:
        cat_fit, cat_note = category_season_fit(category, sk, climate)

    return {
        "destination": destination,
        "as_of": when.isoformat(),
        "hemisphere": hem,
        "climate_code": climate,
        "climate_label_ja": climate_label(destination),
        "local_season_key": sk,
        "local_season_ja": sl,
        "hemisphere_note": (
            "南半球の国は、北半球と**季節が逆**です（12〜2月が夏の国も）。"
            if hem == "south"
            else "北半球の暦で季節を推定しています。"
            if hem == "north"
            else "赤道付近は雨季・乾季の方が生活に効く場合があります。"
        ),
        "need_insights_ja": needs,
        "category_fit_multiplier": cat_fit,
        "category_fit_note": cat_note,
    }


def format_climate_report(ctx: dict[str, Any]) -> str:
    lines = [
        "━" * 62,
        "  気候・現地季節（半球・寒暖）",
        "━" * 62,
        f"  仕向け: {ctx['destination']}",
        f"  基準日: {ctx['as_of']}",
        f"  気候帯: {ctx['climate_label_ja']} ({ctx['climate_code']})",
        f"  現地の季節感: {ctx['local_season_ja']}（内部キー: {ctx['local_season_key']}）",
        f"  半球: {ctx['hemisphere']}",
        "",
        f"  {ctx['hemisphere_note']}",
        "",
        "  【その時期に増えやすいニーズ（目安）】",
    ]
    for n in ctx["need_insights_ja"]:
        lines.append(f"    ・{n}")
    if ctx.get("category_fit_note"):
        lines.extend([
            "",
            f"  選択カテゴリの季節相性係数: ×{ctx['category_fit_multiplier']}",
            f"  {ctx['category_fit_note']}",
        ])
    lines.append("━" * 62)
    return "\n".join(lines)
