"""
profit_tools.py — eBay 輸出向け「送料・関税・利益」統合計算ツール

yen_factors.py の calc_ebay_profit を拡張し、
  1. 重量と仕向地から国際送料を自動見積（EMS/DHL）
  2. カテゴリと仕向地から関税・VAT を自動見積（DDP自分持ちの場合）
  3. 目標ROIを達成するための最低販売価格を逆算
  4. これらを統合した「1発で全部やる」関数 calc_unified を提供
"""

from __future__ import annotations

from typing import Optional


# ════════════════════════════════════════════════
#  eBay / 受取手数料のデフォルト（2026年時点）
# ════════════════════════════════════════════════
DEFAULT_EBAY_FEE_RATE = 0.1325       # eBay Final Value Fee 13.25%
DEFAULT_PAYONEER_FEE_RATE = 0.02     # Payoneer 受取手数料目安 2%
DEFAULT_INTL_FEE_RATE = 0.0165       # International fee 1.65%


# ════════════════════════════════════════════════
#  介入リスク水準
# ════════════════════════════════════════════════
INTERVENTION_LEVELS_USDJPY = {
    "warning": 152.00,
    "intervention_likely": 155.00,
}


def _fetch_usdjpy() -> Optional[float]:
    """yfinance から USD/JPY 現在値を取得（利用不可なら None）"""
    try:
        import yfinance as yf
        t = yf.Ticker("USDJPY=X")
        df = t.history(period="5d", interval="1d")
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def get_intervention_warning(usdjpy: Optional[float]) -> Optional[dict]:
    """ドル円水準から介入リスクを返す"""
    if usdjpy is None:
        return None
    lv = INTERVENTION_LEVELS_USDJPY
    if usdjpy >= lv["intervention_likely"]:
        return {"level": "高",
                "message": f"{lv['intervention_likely']}円超 → 実弾介入の可能性極めて高い"}
    if usdjpy >= lv["warning"]:
        return {"level": "中",
                "message": f"{lv['warning']}円超 → 財務省・口先介入リスク"}
    return {"level": "低",
            "message": f"介入水準（{lv['warning']}円）まで余裕あり"}


# ════════════════════════════════════════════════
#  仕入れ先プリセット
# ════════════════════════════════════════════════
SOURCES = {
    "yahoo_auction": {"name": "Yahoo!オークション",
                      "typical_margin": "40〜80%（骨董・絶版で100%超も）"},
    "yahoo_shopping": {"name": "Yahoo!ショッピング", "typical_margin": "20〜40%"},
    "rakuten": {"name": "楽天市場", "typical_margin": "20〜40%"},
    "amazon_jp": {"name": "Amazon.co.jp", "typical_margin": "15〜35%"},
    "mercari": {"name": "メルカリ", "typical_margin": "30〜70%"},
    "surugaya": {"name": "駿河屋", "typical_margin": "40〜80%"},
    "fanvi_terauchi": {"name": "ファンビ寺内", "typical_margin": "40〜60%"},
    "superdelivery": {"name": "スーパーデリバリー", "typical_margin": "30〜60%"},
    "kosendo": {"name": "古書店・骨董市", "typical_margin": "50〜200%"},
    "home_center": {"name": "ホームセンター・量販（小売）",
                      "typical_margin": "10〜25%（定価比で薄い）"},
    "wholesale_b2b": {"name": "問屋・B2B・業者卸",
                       "typical_margin": "25〜50%（定価の6〜7割仕入れが現実的なことが多い）"},
    "auction_clearance": {"name": "オークション・在庫処分・閉店",
                          "typical_margin": "30〜70%（品により）"},
}


# ════════════════════════════════════════════════
#  カテゴリ別 想定利益率
# ════════════════════════════════════════════════
CATEGORIES = {
    "骨董品・浮世絵":     "50〜200%",
    "骨董品・陶磁器":     "40〜120%",
    "骨董品・茶道具":     "50〜150%",
    "骨董品・漆器・蒔絵": "50〜150%",
    "骨董品・仏像・仏具": "60〜200%",
    "骨董品・着物・帯":   "40〜100%",
    "骨董品・古銭・切手": "30〜300%",
    "骨董品・古書":       "30〜150%",
    "骨董品・刀剣":       "60〜150%",
    "カメラ・レンズ":     "30〜70%",
    "時計":               "30〜60%",
    "楽器":               "40〜80%",
    "ホビー・フィギュア": "30〜60%",
    "ホビー・ガンプラ":   "30〜80%",
    "ホビー・ポケモンカード": "40〜100%",
    "ゲーム":             "40〜100%",
    "ファッション":       "40〜60%",
    "包丁・キッチン":     "50%〜",
    "化粧品":             "20〜40%",
    "建材・DIY・補修材":  "25〜55%",
    "防水・シーリング・塗料": "20〜45%",
}

# 化学系建材の輸出はツールの数値以外に法令・危険物・プラットフォーム規約の確認が必須
BUILDING_CHEMICAL_EXPORT_NOTES = """
【防水剤・シーリング・塗装・サビ止め等の輸出で必ず確認すること】
・航空・船便ともに「危険物」「可燃」「エアゾール」区分で送れない・追加料金が重い場合が多い。
・各国で化学物質登録（例: TSCA, REACH, 化審法）や SDS/ラベル言語の要件がある。
・eBay 等では特定の塗料・溶剤が禁止またはカテゴリ制限のことがある。
・「小売定価の30〜40%引きで仕入れ」は一般消費者向け店頭では稀。実現しやすいのは
  業者卸・まとめ買い・型落ち・在庫処分・オークション等。無理に怪しいルートは避ける。
・原油・中東・需給の見通しは日々変わる。在庫戦略は一次情報（メーカー・問屋・実需）で確認。
"""

# ツールの例示・ヒントから「省く」品目（互換充電・ケーブル等・薄利多売・規制リスク）
EXPORT_OMITTED_PRODUCTS_NOTE = """
【輸出の優先例から省いているもの（参考）】
・互換充電器・USBケーブル・ACアダプタ・モバイルバッテリ等の汎用電源まわり
・型番が細かく陳腐化しやすい安価ガジェット全般
・送料・返品・安全規制（PSE・リチウム等）で利益が出にくい小型電子
※ 本ツールのカテゴリ・イベントヒントからも上記方向の推奨は除外しています。
"""


# ════════════════════════════════════════════════
#  基本の利益計算（送料・関税抜き）
# ════════════════════════════════════════════════
def calc_ebay_profit(
    cost_jpy: float,
    sell_price_usd: float,
    product_name: str = "",
    sku: str = "",
    category: str = "",
    source: str = "",
    shipping_usd: float = 0.0,
    shipping_cost_jpy: float = 0.0,
    extra_cost_jpy: float = 0.0,
    ebay_fee_rate: float = DEFAULT_EBAY_FEE_RATE,
    payoneer_fee_rate: float = DEFAULT_PAYONEER_FEE_RATE,
    intl_fee_rate: float = DEFAULT_INTL_FEE_RATE,
    usdjpy: Optional[float] = None,
) -> dict:
    """eBay輸出の利益を計算（単体版）"""
    if usdjpy is None:
        usdjpy = _fetch_usdjpy()
        if usdjpy is None:
            raise RuntimeError("USD/JPY 取得失敗。引数 usdjpy を指定してください。")

    gross_usd = sell_price_usd + shipping_usd
    total_fee_rate = ebay_fee_rate + payoneer_fee_rate + intl_fee_rate
    fee_usd = gross_usd * total_fee_rate
    net_usd = gross_usd - fee_usd

    revenue_jpy = net_usd * usdjpy
    cost_total_jpy = cost_jpy + shipping_cost_jpy + extra_cost_jpy
    profit_jpy = revenue_jpy - cost_total_jpy

    margin = (profit_jpy / revenue_jpy * 100) if revenue_jpy > 0 else 0
    roi = (profit_jpy / cost_total_jpy * 100) if cost_total_jpy > 0 else 0

    intervention = get_intervention_warning(usdjpy)

    if intervention and intervention["level"] == "高":
        timing = "介入警戒：在庫を早めに売却推奨"
    elif usdjpy and usdjpy >= 150:
        timing = "円安圏：販売有利"
    else:
        timing = "通常水準"

    if profit_jpy <= 0:
        judge = "STOP"
    elif roi >= 30:
        judge = "GO"
    elif roi >= 15:
        judge = "HOLD"
    else:
        judge = "STOP"

    source_display = SOURCES[source]["name"] if source in SOURCES else source

    return {
        "product_name": product_name,
        "sku": sku,
        "category": category,
        "source": source_display,
        "usdjpy": round(usdjpy, 3),
        "revenue_usd": round(gross_usd, 2),
        "fee_usd": round(fee_usd, 2),
        "net_usd": round(net_usd, 2),
        "revenue_jpy": round(revenue_jpy),
        "cost_total_jpy": round(cost_total_jpy),
        "profit_jpy": round(profit_jpy),
        "margin_pct": round(margin, 1),
        "roi_pct": round(roi, 1),
        "timing": timing,
        "intervention_risk": intervention,
        "judge": judge,
    }


# ════════════════════════════════════════════════
#  国際送料テーブル（日本郵便 EMS を基準にした目安）
#  2025〜2026年時点の一般的な料金。実際は郵便局サイトで最新確認推奨。
# ════════════════════════════════════════════════

# 仕向地→ゾーン対応表
DESTINATION_ZONE = {
    # 第1地帯：東アジア
    "中国": 1, "韓国": 1, "台湾": 1,
    # 第2地帯：北米・中米・中近東・オセアニア・東南アジア
    "US": 2, "アメリカ": 2, "USA": 2,
    "カナダ": 2, "メキシコ": 2,
    "オーストラリア": 2, "AU": 2,
    "ニュージーランド": 2, "NZ": 2,
    "タイ": 2, "ベトナム": 2, "マレーシア": 2,
    "シンガポール": 2, "フィリピン": 2, "インドネシア": 2,
    "UAE": 2, "サウジアラビア": 2,
    # 第3地帯：ヨーロッパ
    "イギリス": 3, "UK": 3, "GB": 3,
    "ドイツ": 3, "DE": 3, "フランス": 3, "FR": 3,
    "イタリア": 3, "IT": 3, "スペイン": 3, "ES": 3,
    "オランダ": 3, "NL": 3, "ベルギー": 3,
    "スイス": 3, "スウェーデン": 3, "EU": 3,
    # 第4地帯：南米・アフリカ
    "ブラジル": 4, "BR": 4,
    "アルゼンチン": 4, "チリ": 4,
    "南アフリカ": 4, "エジプト": 4,
}

# EMS 料金（円）：(上限g, 料金) のタプル。上限g以内なら記載料金。
# ざっくり丸めた目安（2026年時点）
EMS_RATES = {
    1: [  # 第1地帯
        (500, 1450), (600, 1600), (700, 1750), (800, 1900),
        (900, 2050), (1000, 2200), (1250, 2500), (1500, 2800),
        (1750, 3100), (2000, 3400), (2500, 4000), (3000, 4600),
        (4000, 5800), (5000, 7000), (10000, 13000), (20000, 26000),
        (30000, 39000),
    ],
    2: [  # 第2地帯（アメリカ、オーストラリア等）
        (500, 2400), (600, 2700), (700, 3000), (800, 3300),
        (900, 3600), (1000, 3900), (1250, 4500), (1500, 5100),
        (1750, 5700), (2000, 6300), (2500, 7500), (3000, 8700),
        (4000, 11100), (5000, 13500), (10000, 25500), (20000, 49500),
        (30000, 73500),
    ],
    3: [  # 第3地帯（ヨーロッパ）
        (500, 2800), (600, 3200), (700, 3600), (800, 4000),
        (900, 4400), (1000, 4800), (1250, 5500), (1500, 6200),
        (1750, 6900), (2000, 7600), (2500, 9000), (3000, 10400),
        (4000, 13200), (5000, 16000), (10000, 30000), (20000, 58000),
        (30000, 86000),
    ],
    4: [  # 第4地帯（南米・アフリカ）
        (500, 3150), (600, 3600), (700, 4050), (800, 4500),
        (900, 4950), (1000, 5400), (1250, 6200), (1500, 7000),
        (1750, 7800), (2000, 8600), (2500, 10200), (3000, 11800),
        (4000, 15000), (5000, 18200), (10000, 34200), (20000, 66200),
        (30000, 98200),
    ],
}

# DHL/FedEx の目安倍率（EMSの約1.3倍〜1.5倍、速いが高い）
DHL_MULTIPLIER = 1.4
SAL_MULTIPLIER = 0.55       # 小形包装物SAL相当（遅いが安い）
EPACKET_MULTIPLIER = 0.65   # eパケット相当


def estimate_shipping(
    weight_g: float,
    destination: str = "アメリカ",
    method: str = "EMS",
) -> dict:
    """
    重量と仕向地から国際送料を見積もる

    Args:
        weight_g: 商品の総重量（g、梱包材込み推奨）
        destination: 仕向地（例 "アメリカ" / "US" / "ドイツ" など）
        method: "EMS" | "DHL" | "SAL" | "eパケット"

    Returns:
        {"cost_jpy": 見積額, "zone": 地帯, "method": 使用方法,
         "destination": 仕向地, "note": 補足}
    """
    zone = DESTINATION_ZONE.get(destination)
    if zone is None:
        # 見つからない場合は最も高い第3地帯を保守的に採用
        zone = 3
        note = f"『{destination}』が地帯表に無いため第3地帯として計算"
    else:
        note = ""

    table = EMS_RATES[zone]

    # 重量に応じた料金を検索
    ems_cost = None
    for limit_g, price in table:
        if weight_g <= limit_g:
            ems_cost = price
            break

    if ems_cost is None:
        # 30kg超過は扱い不可（小形包装物・EMSの上限）
        return {
            "cost_jpy": None,
            "zone": zone,
            "method": method,
            "destination": destination,
            "error": "重量が EMS 上限（30kg）を超過",
        }

    # 手段別の係数適用
    multiplier = {
        "EMS": 1.0,
        "DHL": DHL_MULTIPLIER,
        "FedEx": DHL_MULTIPLIER,
        "SAL": SAL_MULTIPLIER,
        "eパケット": EPACKET_MULTIPLIER,
    }.get(method, 1.0)

    cost = int(round(ems_cost * multiplier))

    return {
        "cost_jpy": cost,
        "zone": zone,
        "method": method,
        "destination": destination,
        "ems_base": ems_cost,
        "note": note,
    }


# ════════════════════════════════════════════════
#  関税・VAT テーブル（DDP：自分で関税を負担する場合用）
#  通常は購入者負担（DDU）だが、高額商品やクレーム回避で
#  セラー負担にするパターンを想定
# ════════════════════════════════════════════════

# カテゴリ別 関税率（米国を基準、他国もおおむね近い）
# 骨董品（100年以上前）は HS Code 9706 で多くの国が非課税
TARIFF_RATES = {
    # ─── 骨董品系（多くの国で非課税 or 低率） ─
    "骨董品・浮世絵":     {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・陶磁器":     {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・茶道具":     {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・漆器・蒔絵": {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・仏像・仏具": {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・着物・帯":   {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・古銭・切手": {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・古書":       {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "骨董品・刀剣":       {"US": 2.8, "EU": 2.7, "UK": 2.7, "CA": 6.5, "AU": 5},

    # ─── カメラ・光学 ─
    "カメラ・レンズ":     {"US": 0, "EU": 4.2, "UK": 0, "CA": 0, "AU": 5},
    "カメラ":             {"US": 0, "EU": 4.2, "UK": 0, "CA": 0, "AU": 5},

    # ─── 時計 ─
    "時計":               {"US": 0, "EU": 4.5, "UK": 4.5, "CA": 5, "AU": 5},

    # ─── ホビー系 ─
    "ホビー・フィギュア": {"US": 0, "EU": 4.7, "UK": 0, "CA": 0, "AU": 5},
    "ホビー・ガンプラ":   {"US": 0, "EU": 4.7, "UK": 0, "CA": 0, "AU": 5},
    "ホビー・トレカ":     {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "ホビー・ポケモンカード": {"US": 0, "EU": 0, "UK": 0, "CA": 0, "AU": 0},
    "ゲーム":             {"US": 0, "EU": 2.7, "UK": 0, "CA": 0, "AU": 5},

    # ─── 楽器 ─
    "楽器":               {"US": 0, "EU": 3.2, "UK": 3.2, "CA": 6, "AU": 5},

    # ─── ファッション・衣類 ─
    "ファッション":       {"US": 16, "EU": 12, "UK": 12, "CA": 18, "AU": 10},
    "衣類":               {"US": 16, "EU": 12, "UK": 12, "CA": 18, "AU": 10},

    # ─── 食品・化粧品 ─
    "化粧品":             {"US": 0, "EU": 0, "UK": 0, "CA": 6.5, "AU": 5},
    "食品":               {"US": 3, "EU": 8, "UK": 8, "CA": 5, "AU": 5},

    # ─── 包丁・金物 ─
    "包丁・キッチン":     {"US": 0, "EU": 2.7, "UK": 2.7, "CA": 7, "AU": 5},
}

# VAT（付加価値税）※DDPの場合に実質買い手へ転嫁されるコスト
VAT_RATES = {
    "US": 0,       # 連邦VATなし。州税は eBay が自動徴収。
    "EU": 19,      # 平均（19〜25%）
    "UK": 20,
    "CA": 5,       # GST連邦分（州税別途）
    "AU": 10,      # GST
}

# 低額免税（De Minimis）— この金額以下なら関税・VAT免除される場合あり
# 2025年以降、米国は免税枠を廃止したので注意
DE_MINIMIS = {
    "US": 0,       # 2025/5以降、免税枠廃止
    "EU": 150,     # 関税のみ免除。VATは IOSS で徴収
    "UK": 0,       # VATは一律対象（£135以下は eBay 徴収）
    "CA": 20,      # CAD換算で約$15
    "AU": 1000,    # AUD換算で約$660
}


def estimate_tariff(
    value_usd: float,
    category: str,
    destination: str = "US",
    include_vat: bool = True,
) -> dict:
    """
    関税・VAT を見積もる（DDP＝セラー負担シミュレーション用）

    Args:
        value_usd: 申告価格（商品価格＋送料）$
        category: カテゴリ名（TARIFF_RATES のキー）
        destination: "US" / "EU" / "UK" / "CA" / "AU" 等
        include_vat: VAT も加算するか（通常TRUE、DDPならTRUE）

    Returns:
        {"tariff_usd", "vat_usd", "total_usd",
         "tariff_rate", "vat_rate", "de_minimis_applied", ...}
    """
    # 仕向地コードの正規化
    dest_code = destination.upper() if destination else "US"
    alias = {
        "アメリカ": "US", "USA": "US",
        "イギリス": "UK", "GB": "UK",
        "ドイツ": "EU", "フランス": "EU", "イタリア": "EU",
        "スペイン": "EU", "オランダ": "EU", "ベルギー": "EU",
        "カナダ": "CA",
        "オーストラリア": "AU",
    }
    dest_code = alias.get(destination, dest_code)

    # 低額免税チェック
    de_min = DE_MINIMIS.get(dest_code, 0)
    de_min_applied = value_usd < de_min if de_min > 0 else False

    # 関税率
    cat_rates = TARIFF_RATES.get(category, {})
    tariff_rate = cat_rates.get(dest_code, 5.0)  # 不明なら保守的に5%

    # VAT率
    vat_rate = VAT_RATES.get(dest_code, 0) if include_vat else 0

    if de_min_applied:
        tariff_usd = 0
        vat_usd = 0
    else:
        tariff_usd = value_usd * tariff_rate / 100
        # VATは (商品価格 + 関税) に課税される国が多い
        vat_base = value_usd + tariff_usd
        vat_usd = vat_base * vat_rate / 100

    return {
        "tariff_usd": round(tariff_usd, 2),
        "vat_usd": round(vat_usd, 2),
        "total_usd": round(tariff_usd + vat_usd, 2),
        "tariff_rate": tariff_rate,
        "vat_rate": vat_rate,
        "destination_code": dest_code,
        "de_minimis_threshold": de_min,
        "de_minimis_applied": de_min_applied,
        "category_matched": category in TARIFF_RATES,
    }


# ════════════════════════════════════════════════
#  統合関数：calc_unified
# ════════════════════════════════════════════════

def calc_unified(
    cost_jpy: float,
    sell_price_usd: float,
    weight_g: float,
    category: str,
    destination: str = "アメリカ",
    product_name: str = "",
    sku: str = "",
    source: str = "",
    shipping_method: str = "EMS",
    seller_pays_tariff: bool = False,
    packing_cost_jpy: float = 300,
    usdjpy: Optional[float] = None,
    target_roi: float = 30.0,
) -> dict:
    """
    重量・仕向地・カテゴリだけ入れれば送料も関税も自動で込みにして
    利益判定する、ワンストップ計算関数。

    Args:
        cost_jpy: 仕入れ値（円）
        sell_price_usd: eBay販売価格（$）
        weight_g: 総重量（g、梱包込み推奨）
        category: カテゴリ名
        destination: 仕向地（"アメリカ"/"US"/"ドイツ" 等）
        product_name: 商品名（任意）
        sku: SKU（任意）
        source: 仕入れ先（任意）
        shipping_method: "EMS"/"DHL"/"SAL"/"eパケット"
        seller_pays_tariff: Trueならセラーが関税・VATを負担（DDP）
        packing_cost_jpy: 梱包資材費
        usdjpy: ドル円（Noneなら自動取得）
        target_roi: 目標 ROI (%)

    Returns:
        calc_ebay_profit の結果に、送料・関税・最低販売価格を加えたもの
    """
    # ── USD/JPY 取得（1回だけ）
    if usdjpy is None:
        usdjpy = _fetch_usdjpy()
        if usdjpy is None:
            raise RuntimeError("USD/JPY 取得失敗")

    # ── 送料自動見積
    ship = estimate_shipping(weight_g, destination, shipping_method)
    shipping_cost_jpy = ship["cost_jpy"] or 0

    # ── 関税自動見積（DDPなら自分持ち）
    tariff_info = estimate_tariff(
        value_usd=sell_price_usd,
        category=category,
        destination=destination,
        include_vat=seller_pays_tariff,
    )
    tariff_cost_jpy = 0
    if seller_pays_tariff:
        tariff_cost_jpy = tariff_info["total_usd"] * usdjpy

    # ── 既存 calc_ebay_profit を呼び出し
    result = calc_ebay_profit(
        cost_jpy=cost_jpy,
        sell_price_usd=sell_price_usd,
        product_name=product_name,
        sku=sku,
        category=category,
        source=source,
        shipping_usd=0,  # 送料込み価格想定（sell_price_usdに含む前提）
        shipping_cost_jpy=shipping_cost_jpy,
        extra_cost_jpy=packing_cost_jpy + tariff_cost_jpy,
        usdjpy=usdjpy,
    )

    # ── 目標ROIを達成する最低販売価格を逆算
    min_price = calc_minimum_sell_price(
        cost_jpy=cost_jpy,
        weight_g=weight_g,
        category=category,
        destination=destination,
        target_roi=target_roi,
        seller_pays_tariff=seller_pays_tariff,
        packing_cost_jpy=packing_cost_jpy,
        usdjpy=usdjpy,
        shipping_method=shipping_method,
    )

    # 結果を統合
    result.update({
        "destination": destination,
        "weight_g": weight_g,
        "shipping_method": shipping_method,
        "shipping_cost_jpy": shipping_cost_jpy,
        "shipping_zone": ship["zone"],
        "seller_pays_tariff": seller_pays_tariff,
        "tariff_info": tariff_info,
        "tariff_cost_jpy": round(tariff_cost_jpy),
        "packing_cost_jpy": packing_cost_jpy,
        "min_sell_price_usd": min_price["min_sell_price_usd"],
        "target_roi": target_roi,
        "price_vs_minimum": round(sell_price_usd - min_price["min_sell_price_usd"], 2),
    })

    return result


def calc_minimum_sell_price(
    cost_jpy: float,
    weight_g: float,
    category: str,
    destination: str = "アメリカ",
    target_roi: float = 30.0,
    seller_pays_tariff: bool = False,
    packing_cost_jpy: float = 300,
    usdjpy: Optional[float] = None,
    shipping_method: str = "EMS",
    ebay_fee_rate: float = DEFAULT_EBAY_FEE_RATE,
    payoneer_fee_rate: float = DEFAULT_PAYONEER_FEE_RATE,
    intl_fee_rate: float = DEFAULT_INTL_FEE_RATE,
) -> dict:
    """
    目標ROI（コスト比利益率）を達成する最低販売価格（USD）を逆算する。

    式の組み立て：
      cost_total_jpy = 仕入れ + 送料 + 梱包 + 関税(DDPなら)
      必要な円換算純利益 = cost_total_jpy * target_roi/100
      必要な円換算売上 = cost_total_jpy * (1 + target_roi/100)
      必要な手取りUSD = 売上円 / usdjpy
      販売価格$ = 手取り / (1 - 手数料率)  ※関税込みの場合は繰り返し調整
    """
    if usdjpy is None:
        usdjpy = _fetch_usdjpy()
        if usdjpy is None:
            raise RuntimeError("USD/JPY 取得失敗")

    ship = estimate_shipping(weight_g, destination, shipping_method)
    shipping_cost_jpy = ship["cost_jpy"] or 0

    fee_rate = ebay_fee_rate + payoneer_fee_rate + intl_fee_rate

    # 関税を含まない基本部分
    base_cost_jpy = cost_jpy + shipping_cost_jpy + packing_cost_jpy

    # 関税はDDPの場合、sell_price に比例してかかる → 反復計算が必要
    # ここでは数回ループして収束させる（5回で十分収束）
    sell_price_usd = 0.0
    tariff_cost_jpy = 0.0
    for _ in range(10):
        total_cost_jpy = base_cost_jpy + tariff_cost_jpy
        required_revenue_jpy = total_cost_jpy * (1 + target_roi / 100)
        required_net_usd = required_revenue_jpy / usdjpy
        sell_price_usd = required_net_usd / (1 - fee_rate)

        if seller_pays_tariff:
            tariff_info = estimate_tariff(
                value_usd=sell_price_usd,
                category=category,
                destination=destination,
                include_vat=True,
            )
            new_tariff_cost_jpy = tariff_info["total_usd"] * usdjpy
            if abs(new_tariff_cost_jpy - tariff_cost_jpy) < 1:
                tariff_cost_jpy = new_tariff_cost_jpy
                break
            tariff_cost_jpy = new_tariff_cost_jpy
        else:
            break

    return {
        "min_sell_price_usd": round(sell_price_usd, 2),
        "usdjpy_used": round(usdjpy, 3),
        "shipping_cost_jpy": shipping_cost_jpy,
        "tariff_cost_jpy": round(tariff_cost_jpy) if seller_pays_tariff else 0,
        "total_cost_jpy": round(base_cost_jpy + tariff_cost_jpy),
        "target_roi_pct": target_roi,
        "destination": destination,
        "category": category,
    }


# ════════════════════════════════════════════════
#  レポート整形
# ════════════════════════════════════════════════

def format_unified_report(r: dict) -> str:
    """calc_unified の結果を日本語の総合レポートに整形"""
    L = []
    L.append("╔══════════════════════════════════════════════╗")
    L.append("║  eBay 輸出 統合利益シミュレーション              ║")
    L.append("╚══════════════════════════════════════════════╝")

    if r.get("product_name"):
        L.append(f" 商品名        : {r['product_name']}")
    if r.get("sku"):
        L.append(f" SKU           : {r['sku']}")
    if r.get("category"):
        L.append(f" カテゴリ      : {r['category']}")
    if r.get("source"):
        L.append(f" 仕入れ先      : {r['source']}")
    L.append(f" 仕向地        : {r.get('destination', '—')}  "
             f"(ゾーン {r.get('shipping_zone', '—')})")
    L.append(f" 重量          : {r.get('weight_g', '—')} g")
    L.append(f" 発送方法      : {r.get('shipping_method', '—')}")
    L.append(f" 現在のUSD/JPY : {r['usdjpy']} 円")
    L.append("───────────────────────────────────────────────")
    L.append(" 【コスト内訳】")
    L.append(f"   仕入れ値        : ¥{r['cost_total_jpy'] - r.get('shipping_cost_jpy', 0) - r.get('packing_cost_jpy', 0) - r.get('tariff_cost_jpy', 0):,}")
    L.append(f"   国際送料        : ¥{r.get('shipping_cost_jpy', 0):,}")
    L.append(f"   梱包・資材      : ¥{r.get('packing_cost_jpy', 0):,}")
    if r.get("seller_pays_tariff"):
        ti = r.get("tariff_info", {})
        L.append(f"   関税(DDP)       : ¥{r.get('tariff_cost_jpy', 0):,} "
                 f"[関税{ti.get('tariff_rate', 0)}% / VAT{ti.get('vat_rate', 0)}%]")
    else:
        ti = r.get("tariff_info", {})
        L.append(f"   関税            : 購入者負担（参考: 関税{ti.get('tariff_rate', 0)}% / VAT{ti.get('vat_rate', 0)}%）")
    L.append(f"   合計コスト      : ¥{r['cost_total_jpy']:,}")
    L.append("───────────────────────────────────────────────")
    L.append(" 【売上・利益】")
    L.append(f"   eBay売上($)      : ${r['revenue_usd']:.2f}")
    L.append(f"   手数料($)        : ${r['fee_usd']:.2f}")
    L.append(f"   手取り($)        : ${r['net_usd']:.2f}")
    L.append(f"   円換算売上       : ¥{r['revenue_jpy']:,}")
    L.append(f"   純利益           : ¥{r['profit_jpy']:,}")
    L.append(f"   利益率(売上比)   : {r['margin_pct']}%")
    L.append(f"   ROI(投下資金比)  : {r['roi_pct']}%")
    L.append("───────────────────────────────────────────────")
    L.append(" 【最低販売価格】")
    L.append(f"   目標ROI {r['target_roi']}%達成ライン : "
             f"${r['min_sell_price_usd']:.2f}")
    diff = r['price_vs_minimum']
    if diff >= 0:
        L.append(f"   現在価格 − 最低ライン : +${diff:.2f}  ★達成！")
    else:
        L.append(f"   現在価格 − 最低ライン : ${diff:.2f}  ⚠ 不足")
    L.append("───────────────────────────────────────────────")
    judge_mark = {"GO": "[GO] 仕入れ推奨",
                  "HOLD": "[HOLD] 要検討",
                  "STOP": "[STOP] 見送り"}
    L.append(f" 総合判定        : {judge_mark.get(r['judge'], r['judge'])}")
    L.append(f" 為替タイミング  : {r['timing']}")
    if r.get("intervention_risk"):
        ir = r["intervention_risk"]
        L.append(f" 介入リスク      : {ir['level']} - {ir['message']}")
    L.append("═══════════════════════════════════════════════")
    return "\n".join(L)


# ════════════════════════════════════════════════
#  CLI デモ
# ════════════════════════════════════════════════

# ════════════════════════════════════════════════
#  CSV 一括判定ユーティリティ
# ════════════════════════════════════════════════

# CSV で受け付ける列名（日本語・英語どちらでもOK）
CSV_COLUMN_ALIAS = {
    # 商品情報
    "商品名": "product_name", "product_name": "product_name", "name": "product_name",
    "SKU": "sku", "sku": "sku", "管理コード": "sku",
    "カテゴリ": "category", "category": "category",
    "仕入れ先": "source", "source": "source",
    # 価格・重量
    "仕入れ値": "cost_jpy", "仕入値": "cost_jpy", "仕入価格": "cost_jpy",
    "cost_jpy": "cost_jpy", "cost": "cost_jpy",
    "販売価格": "sell_price_usd", "販売価格USD": "sell_price_usd",
    "sell_price_usd": "sell_price_usd", "price_usd": "sell_price_usd",
    "想定販売価格": "sell_price_usd",
    "重量": "weight_g", "重量g": "weight_g",
    "weight_g": "weight_g", "weight": "weight_g",
    # 配送・関税
    "仕向地": "destination", "destination": "destination",
    "発送方法": "shipping_method", "shipping_method": "shipping_method",
    "関税負担": "seller_pays_tariff", "seller_pays_tariff": "seller_pays_tariff",
    "目標ROI": "target_roi", "target_roi": "target_roi",
    "梱包費": "packing_cost_jpy", "packing_cost_jpy": "packing_cost_jpy",
}


def _normalize_columns(row: dict) -> dict:
    """CSVの列名を内部キーに正規化"""
    result = {}
    for k, v in row.items():
        key = CSV_COLUMN_ALIAS.get(str(k).strip(), str(k).strip())
        result[key] = v
    return result


def _coerce(value, typ, default=None):
    """値をtype変換（空文字・NaNは default）"""
    try:
        if value is None or str(value).strip() == "" or str(value).lower() == "nan":
            return default
        if typ is bool:
            s = str(value).strip().lower()
            return s in ("1", "true", "yes", "y", "はい", "○", "o")
        return typ(value)
    except (ValueError, TypeError):
        return default


def batch_calc_from_csv(
    input_csv: str,
    output_csv: Optional[str] = None,
    go_only_csv: Optional[str] = None,
    default_destination: str = "アメリカ",
    default_target_roi: float = 30.0,
    default_shipping_method: str = "EMS",
    default_packing_cost_jpy: float = 300,
    usdjpy: Optional[float] = None,
) -> dict:
    """
    CSVから商品リストを読み込み、全商品を calc_unified で判定する

    Args:
        input_csv: 入力CSVパス
        output_csv: 全結果を書き出すCSVパス（None=書き出さない）
        go_only_csv: ROI >= target_roi だけ抽出したCSVパス
        default_destination: 仕向地のデフォルト（行で未指定時）
        default_target_roi: 目標ROI(%)のデフォルト
        default_shipping_method: 発送方法のデフォルト
        default_packing_cost_jpy: 梱包費デフォルト
        usdjpy: ドル円（Noneなら1度だけ取得してキャッシュ）

    Returns:
        {"total": 件数, "go": GO件数, "hold": HOLD, "stop": STOP,
         "best_top3": 上位3商品, "results": 全結果リスト}
    """
    import csv

    # USD/JPY は1回だけ取得してキャッシュ（API節約）
    if usdjpy is None:
        usdjpy = _fetch_usdjpy()
        if usdjpy is None:
            raise RuntimeError("USD/JPY 取得失敗。引数 usdjpy で指定してください。")

    # ── 入力読み込み
    with open(input_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]

    if not rows:
        raise ValueError(f"{input_csv} は空です")

    results = []
    errors = []

    for i, raw in enumerate(rows, start=2):  # 2行目=先頭データ行
        row = _normalize_columns(raw)
        try:
            cost_jpy = _coerce(row.get("cost_jpy"), float)
            sell_usd = _coerce(row.get("sell_price_usd"), float)
            weight_g = _coerce(row.get("weight_g"), float)

            if cost_jpy is None or sell_usd is None or weight_g is None:
                raise ValueError("cost_jpy / sell_price_usd / weight_g は必須")

            res = calc_unified(
                cost_jpy=cost_jpy,
                sell_price_usd=sell_usd,
                weight_g=weight_g,
                category=str(row.get("category", "")).strip(),
                destination=str(row.get("destination", default_destination)).strip()
                            or default_destination,
                product_name=str(row.get("product_name", "")).strip(),
                sku=str(row.get("sku", "")).strip(),
                source=str(row.get("source", "")).strip(),
                shipping_method=str(row.get("shipping_method",
                                             default_shipping_method)).strip()
                                or default_shipping_method,
                seller_pays_tariff=_coerce(row.get("seller_pays_tariff"),
                                           bool, False) or False,
                packing_cost_jpy=_coerce(row.get("packing_cost_jpy"),
                                         float, default_packing_cost_jpy),
                target_roi=_coerce(row.get("target_roi"),
                                   float, default_target_roi),
                usdjpy=usdjpy,
            )
            results.append(res)
        except Exception as e:
            errors.append({"row": i, "error": str(e), "data": raw})

    # ── 集計
    go_count = sum(1 for r in results if r["judge"] == "GO")
    hold_count = sum(1 for r in results if r["judge"] == "HOLD")
    stop_count = sum(1 for r in results if r["judge"] == "STOP")

    # 上位3（ROI順）
    top3 = sorted(results, key=lambda r: r["roi_pct"], reverse=True)[:3]

    # ── CSV出力列
    output_columns = [
        "product_name", "sku", "category", "source",
        "destination", "shipping_method", "weight_g",
        "usdjpy",
        "cost_total_jpy", "shipping_cost_jpy", "packing_cost_jpy",
        "tariff_cost_jpy", "seller_pays_tariff",
        "revenue_usd", "fee_usd", "net_usd", "revenue_jpy",
        "profit_jpy", "margin_pct", "roi_pct",
        "min_sell_price_usd", "price_vs_minimum",
        "judge", "timing",
    ]

    def _flatten(r):
        return {k: r.get(k, "") for k in output_columns}

    # 全結果CSV
    if output_csv:
        with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_columns)
            writer.writeheader()
            for r in results:
                writer.writerow(_flatten(r))

    # GOだけCSV
    if go_only_csv:
        with open(go_only_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_columns)
            writer.writeheader()
            for r in results:
                if r["judge"] == "GO":
                    writer.writerow(_flatten(r))

    return {
        "total": len(results),
        "go": go_count,
        "hold": hold_count,
        "stop": stop_count,
        "errors": errors,
        "best_top3": top3,
        "results": results,
        "usdjpy": usdjpy,
    }


def format_batch_summary(summary: dict) -> str:
    """バッチ結果のサマリーを整形"""
    L = []
    L.append("╔══════════════════════════════════════════════╗")
    L.append("║   CSV一括判定 結果サマリー                     ║")
    L.append("╚══════════════════════════════════════════════╝")
    L.append(f" 現在のUSD/JPY  : {summary['usdjpy']:.3f} 円")
    L.append(f" 処理件数       : {summary['total']} 件")
    L.append(f"   ├ [GO]  仕入推奨 : {summary['go']} 件")
    L.append(f"   ├ [HOLD] 要検討   : {summary['hold']} 件")
    L.append(f"   └ [STOP] 見送り   : {summary['stop']} 件")
    if summary["errors"]:
        L.append(f" エラー         : {len(summary['errors'])} 件")
        for e in summary["errors"][:3]:
            L.append(f"   行{e['row']}: {e['error']}")
    L.append("───────────────────────────────────────────────")
    L.append(" 【利益率 TOP3】")
    for i, r in enumerate(summary["best_top3"], 1):
        name = r.get("product_name", "")[:30] or "(no name)"
        L.append(f"   {i}位 {name}")
        L.append(f"       ROI {r['roi_pct']}% / 利益 ¥{r['profit_jpy']:,} / "
                 f"判定 {r['judge']}")
    L.append("═══════════════════════════════════════════════")
    return "\n".join(L)


def generate_sample_csv(path: str = "sample_products.csv") -> str:
    """サンプルCSVを生成"""
    import csv

    sample_rows = [
        {
            "商品名": "九谷焼 赤絵金彩 花瓶 明治期 共箱付",
            "SKU": "ANT-KUT-001",
            "カテゴリ": "骨董品・陶磁器",
            "仕入れ先": "yahoo_auction",
            "仕入れ値": 12000,
            "想定販売価格": 280,
            "重量g": 1800,
            "仕向地": "アメリカ",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 30,
        },
        {
            "商品名": "Nikon AI-s 50mm f/1.4 レンズ",
            "SKU": "CAM-NIK-001",
            "カテゴリ": "カメラ・レンズ",
            "仕入れ先": "yahoo_auction",
            "仕入れ値": 15000,
            "想定販売価格": 210,
            "重量g": 500,
            "仕向地": "アメリカ",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 30,
        },
        {
            "商品名": "楽焼 黒茶碗 共箱付",
            "SKU": "ANT-TEA-001",
            "カテゴリ": "骨董品・茶道具",
            "仕入れ先": "yahoo_auction",
            "仕入れ値": 25000,
            "想定販売価格": 450,
            "重量g": 1200,
            "仕向地": "イギリス",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 35,
        },
        {
            "商品名": "SEIKO SARB033 自動巻腕時計",
            "SKU": "WAT-SEI-001",
            "カテゴリ": "時計",
            "仕入れ先": "mercari",
            "仕入れ値": 35000,
            "想定販売価格": 380,
            "重量g": 400,
            "仕向地": "ドイツ",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 30,
        },
        {
            "商品名": "ポケモンカード リザードン 1st Ed",
            "SKU": "PKM-001",
            "カテゴリ": "ホビー・ポケモンカード",
            "仕入れ先": "surugaya",
            "仕入れ値": 8000,
            "想定販売価格": 180,
            "重量g": 80,
            "仕向地": "アメリカ",
            "発送方法": "eパケット",
            "関税負担": False,
            "目標ROI": 30,
        },
        {
            "商品名": "西陣織 絹帯 アンティーク",
            "SKU": "ANT-KIM-001",
            "カテゴリ": "骨董品・着物・帯",
            "仕入れ先": "yahoo_auction",
            "仕入れ値": 8000,
            "想定販売価格": 160,
            "重量g": 900,
            "仕向地": "フランス",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 30,
        },
        {
            "商品名": "利益薄赤字テスト品（見送り例）",
            "SKU": "TEST-001",
            "カテゴリ": "化粧品",
            "仕入れ先": "amazon_jp",
            "仕入れ値": 5000,
            "想定販売価格": 45,
            "重量g": 300,
            "仕向地": "アメリカ",
            "発送方法": "EMS",
            "関税負担": False,
            "目標ROI": 30,
        },
    ]

    fieldnames = ["商品名", "SKU", "カテゴリ", "仕入れ先", "仕入れ値",
                  "想定販売価格", "重量g", "仕向地", "発送方法",
                  "関税負担", "目標ROI"]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sample_rows:
            writer.writerow(r)

    return path


# ════════════════════════════════════════════════
#  為替シナリオ分析（USD/JPYを動かして利益変化を見る）
# ════════════════════════════════════════════════

# 分析する為替レートのオフセット（現在値からの差）
DEFAULT_FX_SCENARIOS = [-10, -5, -2, 0, +2, +5, +10]


def scenario_analysis(
    cost_jpy: float,
    sell_price_usd: float,
    weight_g: float,
    category: str,
    destination: str = "アメリカ",
    product_name: str = "",
    shipping_method: str = "EMS",
    seller_pays_tariff: bool = False,
    packing_cost_jpy: float = 300,
    target_roi: float = 30.0,
    current_usdjpy: Optional[float] = None,
    scenarios: Optional[list] = None,
    include_intervention_levels: bool = True,
) -> dict:
    """
    USD/JPY が動いた場合の利益変化をシミュレーションする

    Args:
        cost_jpy, sell_price_usd, weight_g, category, destination:
            calc_unified と同じ
        scenarios: 現在値からのオフセットリスト（円）。例: [-10, -5, 0, +5, +10]
        include_intervention_levels: 介入ライン（152, 155）を自動追加

    Returns:
        {
          "current_usdjpy": 現在値,
          "scenarios": [ {"usdjpy", "offset", "label", "profit_jpy",
                          "roi_pct", "judge", "min_sell_price"} ... ],
          "breakeven_usdjpy": 損益分岐USD/JPY,
          "target_roi_usdjpy": 目標ROI達成に必要なUSD/JPY,
        }
    """
    # ── 現在値の取得
    if current_usdjpy is None:
        current_usdjpy = _fetch_usdjpy()
        if current_usdjpy is None:
            raise RuntimeError("USD/JPY 取得失敗")

    offsets = list(scenarios) if scenarios else list(DEFAULT_FX_SCENARIOS)

    # 介入ライン（絶対値）もシナリオに追加
    extra_points = []
    if include_intervention_levels:
        for lv in (INTERVENTION_LEVELS_USDJPY["warning"],
                   INTERVENTION_LEVELS_USDJPY["intervention_likely"]):
            diff = round(lv - current_usdjpy, 2)
            if abs(diff) <= 20 and diff not in offsets:
                extra_points.append((lv, diff, f"介入ライン({int(lv)})"))

    # ── 各シナリオで計算
    scenario_results = []

    def _eval(usdjpy, label, offset=None):
        res = calc_unified(
            cost_jpy=cost_jpy,
            sell_price_usd=sell_price_usd,
            weight_g=weight_g,
            category=category,
            destination=destination,
            product_name=product_name,
            shipping_method=shipping_method,
            seller_pays_tariff=seller_pays_tariff,
            packing_cost_jpy=packing_cost_jpy,
            target_roi=target_roi,
            usdjpy=usdjpy,
        )
        return {
            "usdjpy": round(usdjpy, 2),
            "offset": offset,
            "label": label,
            "profit_jpy": res["profit_jpy"],
            "margin_pct": res["margin_pct"],
            "roi_pct": res["roi_pct"],
            "judge": res["judge"],
            "min_sell_price_usd": res["min_sell_price_usd"],
        }

    for off in offsets:
        rate = current_usdjpy + off
        if rate <= 50:
            continue
        if off == 0:
            label = "現在"
        elif off > 0:
            label = f"+{off}円（円安）"
        else:
            label = f"{off}円（円高）"
        scenario_results.append(_eval(rate, label, off))

    for rate, diff, label in extra_points:
        scenario_results.append(_eval(rate, label, diff))

    # USD/JPYで並び替え
    scenario_results.sort(key=lambda x: x["usdjpy"])

    # ── 損益分岐USD/JPYの逆算
    #   利益=0 となる USD/JPY を計算
    #   利益_jpy = net_usd * usdjpy - cost_total_jpy = 0
    #   → usdjpy = cost_total_jpy / net_usd
    fee_rate = DEFAULT_EBAY_FEE_RATE + DEFAULT_PAYONEER_FEE_RATE + DEFAULT_INTL_FEE_RATE
    net_usd = sell_price_usd * (1 - fee_rate)
    ship = estimate_shipping(weight_g, destination, shipping_method)
    shipping_cost_jpy = ship["cost_jpy"] or 0
    base_cost_jpy = cost_jpy + shipping_cost_jpy + packing_cost_jpy

    if seller_pays_tariff:
        tariff_info = estimate_tariff(
            value_usd=sell_price_usd,
            category=category,
            destination=destination,
            include_vat=True,
        )
        tariff_cost_jpy_fixed = tariff_info["total_usd"] * current_usdjpy
    else:
        tariff_cost_jpy_fixed = 0
    total_cost_jpy = base_cost_jpy + tariff_cost_jpy_fixed

    breakeven = total_cost_jpy / net_usd if net_usd > 0 else None
    # 目標ROI達成するUSD/JPY：cost*(1+roi/100) = net*usdjpy
    target_rate = total_cost_jpy * (1 + target_roi / 100) / net_usd \
                  if net_usd > 0 else None

    return {
        "current_usdjpy": round(current_usdjpy, 2),
        "target_roi_pct": target_roi,
        "scenarios": scenario_results,
        "breakeven_usdjpy": round(breakeven, 2) if breakeven else None,
        "target_roi_usdjpy": round(target_rate, 2) if target_rate else None,
        "product_name": product_name,
        "category": category,
        "destination": destination,
    }


def format_scenario_report(r: dict) -> str:
    """為替シナリオ分析を表形式で整形"""
    L = []
    L.append("╔══════════════════════════════════════════════╗")
    L.append("║  為替シナリオ分析 — USD/JPY が動いたら?        ║")
    L.append("╚══════════════════════════════════════════════╝")
    if r.get("product_name"):
        L.append(f" 商品      : {r['product_name']}")
    if r.get("category"):
        L.append(f" カテゴリ  : {r['category']}")
    L.append(f" 仕向地    : {r['destination']}")
    L.append(f" 現在レート: {r['current_usdjpy']} 円/$")
    L.append(f" 目標ROI   : {r['target_roi_pct']}%")
    L.append("───────────────────────────────────────────────")
    L.append(f" {'USD/JPY':>8} │ {'シナリオ':<16} │ {'利益(¥)':>10} │ "
             f"{'ROI':>6} │ 判定")
    L.append(" " + "─" * 63)
    for s in r["scenarios"]:
        arrow = ""
        if s["offset"] is not None and s["offset"] > 0:
            arrow = "↑"
        elif s["offset"] is not None and s["offset"] < 0:
            arrow = "↓"
        mark = {"GO": "[GO]  ", "HOLD": "[HOLD]", "STOP": "[STOP]"}.get(s["judge"], "")
        L.append(f" {arrow}{s['usdjpy']:>7.2f} │ {s['label']:<16} │ "
                 f"¥{s['profit_jpy']:>9,} │ {s['roi_pct']:>5.1f}% │ {mark}")
    L.append(" " + "─" * 63)
    L.append("")
    L.append(" 【臨界ライン】")
    if r["breakeven_usdjpy"]:
        L.append(f"   損益分岐USD/JPY      : {r['breakeven_usdjpy']:.2f} 円 "
                 f"(これより円高だと赤字)")
    if r["target_roi_usdjpy"]:
        L.append(f"   ROI{r['target_roi_pct']}%達成ライン : "
                 f"{r['target_roi_usdjpy']:.2f} 円 "
                 f"(これ以上の円安なら目標達成)")
    # 安全マージン
    if r["breakeven_usdjpy"]:
        margin_to_breakeven = r["current_usdjpy"] - r["breakeven_usdjpy"]
        L.append(f"   現在値との余裕      : {margin_to_breakeven:+.2f} 円 "
                 f"(円高への耐性)")
    L.append("═══════════════════════════════════════════════")
    return "\n".join(L)


# ════════════════════════════════════════════════
#  yen_factors との統合：円相場バイアスを加味した判定
# ════════════════════════════════════════════════

def _get_yen_analysis_safe() -> Optional[dict]:
    """yen_factors を安全に呼び出す。失敗時は None"""
    try:
        from yen_factors import analyze_all_factors
        return analyze_all_factors()
    except Exception:
        return None


def calc_unified_with_bias(
    cost_jpy: float,
    sell_price_usd: float,
    weight_g: float,
    category: str,
    destination: str = "アメリカ",
    product_name: str = "",
    sku: str = "",
    source: str = "",
    shipping_method: str = "EMS",
    seller_pays_tariff: bool = False,
    packing_cost_jpy: float = 300,
    usdjpy: Optional[float] = None,
    target_roi: float = 30.0,
    yen_analysis: Optional[dict] = None,
) -> dict:
    """
    calc_unified に「円相場総合バイアス」を加味した強化版。

    円安バイアス強 → GO判定を強化（売り時）
    円高バイアス強 → HOLD判定に格下げ（在庫の目減り警戒）
    """
    # ── 円相場分析を1回取得（省略可。既に持っていれば渡す）
    if yen_analysis is None:
        yen_analysis = _get_yen_analysis_safe()

    # ── USD/JPYが未指定なら analyze から取る
    if usdjpy is None and yen_analysis:
        usdjpy = yen_analysis.get("current_usdjpy")

    # ── 基本計算（calc_unified）
    result = calc_unified(
        cost_jpy=cost_jpy,
        sell_price_usd=sell_price_usd,
        weight_g=weight_g,
        category=category,
        destination=destination,
        product_name=product_name,
        sku=sku,
        source=source,
        shipping_method=shipping_method,
        seller_pays_tariff=seller_pays_tariff,
        packing_cost_jpy=packing_cost_jpy,
        usdjpy=usdjpy,
        target_roi=target_roi,
    )

    # ── 円相場バイアスを加味
    bias_info = None
    judge_original = result["judge"]
    judge_adjusted = judge_original
    action_advice = ""

    if yen_analysis:
        s = yen_analysis["summary"]
        verdict = s["verdict"]
        strength = s["verdict_strength"]
        total_score = s["total_score"]

        bias_info = {
            "verdict": verdict,
            "strength": strength,
            "total_score": total_score,
            "weak_count": s["weak_factors_count"],
            "strong_count": s["strong_factors_count"],
            "top_weak_factors": [r["name"] for r in s["top_weak_factors"][:3]],
            "top_strong_factors": [r["name"] for r in s["top_strong_factors"][:3]],
        }

        # 判定調整ロジック
        if verdict == "円安バイアス" and strength in ("中", "強"):
            if judge_original == "HOLD":
                judge_adjusted = "GO"
                action_advice = "円安バイアスが強い → HOLD→GO に昇格"
            elif judge_original == "GO":
                action_advice = "円安バイアス ☆ 今売るのが最適"
            else:
                action_advice = "円安でも赤字なら仕入れ見送り"
        elif verdict == "円高バイアス" and strength in ("中", "強"):
            if judge_original == "GO" and result["roi_pct"] < 40:
                judge_adjusted = "HOLD"
                action_advice = "円高進行 → 利益が薄い案件はHOLDに格下げ"
            elif judge_original == "GO":
                action_advice = "円高でも高ROIなら十分 → GO維持"
            else:
                action_advice = "円高進行 → 新規仕入れは慎重に"
        else:
            action_advice = "為替中立 → 通常の仕入れ判断でOK"

    result["yen_bias"] = bias_info
    result["judge_original"] = judge_original
    result["judge"] = judge_adjusted
    result["action_advice"] = action_advice

    return result


def format_unified_bias_report(r: dict) -> str:
    """calc_unified_with_bias の結果を日本語レポートに整形"""
    L = []
    L.append(format_unified_report(r))
    # 既存レポートの末尾（═ 線の後）に為替バイアス情報を追記
    if r.get("yen_bias"):
        b = r["yen_bias"]
        L.append("")
        L.append("╔══════════════════════════════════════════════╗")
        L.append("║   円相場バイアス × 仕入れ判定                  ║")
        L.append("╚══════════════════════════════════════════════╝")
        L.append(f" 総合スコア    : {b['total_score']:+.1f}")
        L.append(f" 総合判定      : {b['verdict']}（{b['strength']}）")
        L.append(f"   ├ 円安要因  : {b['weak_count']} 個")
        L.append(f"   └ 円高要因  : {b['strong_count']} 個")
        if b["top_weak_factors"]:
            L.append(f" 円安要因TOP3 : {', '.join(b['top_weak_factors'])}")
        if b["top_strong_factors"]:
            L.append(f" 円高要因TOP3 : {', '.join(b['top_strong_factors'])}")
        L.append("───────────────────────────────────────────────")
        if r.get("judge_original") != r.get("judge"):
            L.append(f" 判定調整      : {r['judge_original']} → {r['judge']}")
        L.append(f" アクション    : {r.get('action_advice', '')}")
        L.append("═══════════════════════════════════════════════")
    return "\n".join(L)


if __name__ == "__main__":
    # ── サンプル1：九谷焼の花瓶（骨董品・陶磁器）を米国へ
    antique = calc_unified(
        product_name="九谷焼 赤絵金彩 花瓶 明治期 共箱付",
        sku="ANT-KUT-001",
        category="骨董品・陶磁器",
        source="yahoo_auction",
        cost_jpy=12000,
        sell_price_usd=280,
        weight_g=1800,          # 陶器は重い
        destination="アメリカ",
        shipping_method="EMS",
        seller_pays_tariff=False,  # 通常は購入者負担
        target_roi=30,
    )
    print(format_unified_report(antique))
    print()

    # ── サンプル2：Nikonレンズを米国へ（DDPで関税自分持ち）
    camera = calc_unified(
        product_name="Nikon AI-s 50mm f/1.4 レンズ",
        sku="CAM-NIK-001",
        category="カメラ・レンズ",
        source="yahoo_auction",
        cost_jpy=15000,
        sell_price_usd=210,
        weight_g=500,
        destination="アメリカ",
        shipping_method="EMS",
        seller_pays_tariff=False,
        target_roi=30,
    )
    print(format_unified_report(camera))
    print()

    # ── サンプル3：茶道具を英国へ
    tea = calc_unified(
        product_name="楽焼 黒茶碗 共箱付",
        category="骨董品・茶道具",
        source="yahoo_auction",
        cost_jpy=25000,
        sell_price_usd=450,
        weight_g=1200,
        destination="イギリス",
        target_roi=35,
    )
    print(format_unified_report(tea))
    print()

    # ── サンプル4：CSV 一括判定デモ
    print("━" * 50)
    print("  CSV 一括判定デモ")
    print("━" * 50)

    sample_path = generate_sample_csv("sample_products.csv")
    print(f"サンプルCSV作成: {sample_path}")

    summary = batch_calc_from_csv(
        input_csv=sample_path,
        output_csv="results_all.csv",
        go_only_csv="results_go_only.csv",
    )
    print(format_batch_summary(summary))
    print()
    print("出力ファイル:")
    print("  - results_all.csv       （全商品 判定結果）")
    print("  - results_go_only.csv   （利益30%以上のGO商品だけ）")
    print()

    # ── サンプル5：為替シナリオ分析
    print("━" * 50)
    print("  為替シナリオ分析デモ")
    print("━" * 50)
    scenario = scenario_analysis(
        product_name="九谷焼 赤絵金彩 花瓶 明治期 共箱付",
        category="骨董品・陶磁器",
        cost_jpy=12000,
        sell_price_usd=280,
        weight_g=1800,
        destination="アメリカ",
        target_roi=30,
    )
    print(format_scenario_report(scenario))
    print()

    # ── サンプル6：円相場バイアスを加味した総合判定
    print("━" * 50)
    print("  円相場バイアス × 仕入れ判定 デモ")
    print("━" * 50)
    print("（全ティッカー取得のため30〜60秒かかります…）")
    bias_result = calc_unified_with_bias(
        product_name="九谷焼 赤絵金彩 花瓶 明治期 共箱付",
        category="骨董品・陶磁器",
        source="yahoo_auction",
        cost_jpy=12000,
        sell_price_usd=280,
        weight_g=1800,
        destination="アメリカ",
        target_roi=30,
    )
    print(format_unified_bias_report(bias_result))
