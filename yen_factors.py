"""
円相場 総合ファクター分析モジュール

円高/円安に影響を与える「考えられるすべての要因」を統合的に取得・分析し、
各ファクターの現在のバイアス（円高/円安方向への寄与）と総合判定を出力する。

【影響要因のカテゴリー】
1. 金融政策・金利差    : FF金利、長短国債利回り差、日銀政策
2. 米ドル指数 (DXY)
3. 資源・エネルギー    : 原油WTI/ブレント、天然ガス、LNG（日本は輸入国）
4. 貴金属・コモディティ: 金、銀、銅、プラチナ
5. 食料・農産物        : 小麦、大豆、コーン、コーヒー
6. リスクセンチメント  : VIX、SKEW、米株（S&P/NASDAQ/ダウ）
7. 株式市場            : 日経225、TOPIX、上海総合
8. クロスレート        : EUR/USD、GBP/USD、AUD/USD、USD/CNH
9. 暗号資産            : Bitcoin（リスク資産バロメーター）
10. 貿易関連          : 海運運賃指数、米中貿易リスク
11. 地政学            : 中東・ウクライナ・台湾海峡・北朝鮮
12. 政府・中銀介入    : 介入実績／介入観測ライン
"""

from datetime import datetime
from typing import Optional


# ════════════════════════════════════════════════
#  円相場に影響するすべての因子定義
#  jpy_impact: そのファクターが「上昇」したときに JPY に与える影響
#    "weak"  = 円安方向
#    "strong" = 円高方向
#    "depends" = 状況依存（個別ロジックで判定）
# ════════════════════════════════════════════════

YEN_FACTORS = {
    # ─── 1. 金利・国債利回り ─────────────────────────
    "金利・国債": {
        "^TNX":  {"name": "米国10年債利回り",     "jpy_impact": "weak",  "weight": 5, "unit": "%"},
        "^FVX":  {"name": "米国 5年債利回り",     "jpy_impact": "weak",  "weight": 4, "unit": "%"},
        "^IRX":  {"name": "米国13週TB利回り",     "jpy_impact": "weak",  "weight": 3, "unit": "%"},
        "^TYX":  {"name": "米国30年債利回り",     "jpy_impact": "weak",  "weight": 4, "unit": "%"},
    },

    # ─── 2. 米ドル指数 ─────────────────────────────
    "米ドル指数": {
        "DX-Y.NYB": {"name": "ドルインデックス (DXY)", "jpy_impact": "weak", "weight": 5, "unit": ""},
    },

    # ─── 3. 資源・エネルギー（日本は輸入国 → 高騰=貿易赤字=円安） ─
    "資源・エネルギー": {
        "CL=F": {"name": "WTI原油先物",       "jpy_impact": "weak", "weight": 5, "unit": "$"},
        "BZ=F": {"name": "ブレント原油先物",  "jpy_impact": "weak", "weight": 5, "unit": "$"},
        "NG=F": {"name": "天然ガス先物",      "jpy_impact": "weak", "weight": 4, "unit": "$"},
        "HO=F": {"name": "ヒーティングオイル", "jpy_impact": "weak", "weight": 2, "unit": "$"},
        "RB=F": {"name": "ガソリン先物",      "jpy_impact": "weak", "weight": 2, "unit": "$"},
    },

    # ─── 4. 貴金属（安全資産=円高方向と相関） ──────
    "貴金属・コモディティ": {
        "GC=F": {"name": "金（ゴールド）",       "jpy_impact": "strong",  "weight": 4, "unit": "$"},
        "SI=F": {"name": "銀（シルバー）",       "jpy_impact": "strong",  "weight": 2, "unit": "$"},
        "PL=F": {"name": "プラチナ",             "jpy_impact": "depends", "weight": 2, "unit": "$"},
        "HG=F": {"name": "銅（ドクターカッパー）", "jpy_impact": "weak",  "weight": 3, "unit": "$"},
    },

    # ─── 5. 食料・農産物（輸入インフレ要因） ───────
    "食料・農産物": {
        "ZW=F": {"name": "小麦",         "jpy_impact": "weak", "weight": 2, "unit": "¢"},
        "ZS=F": {"name": "大豆",         "jpy_impact": "weak", "weight": 2, "unit": "¢"},
        "ZC=F": {"name": "とうもろこし", "jpy_impact": "weak", "weight": 2, "unit": "¢"},
        "KC=F": {"name": "コーヒー",     "jpy_impact": "weak", "weight": 1, "unit": "¢"},
        "SB=F": {"name": "砂糖",         "jpy_impact": "weak", "weight": 1, "unit": "¢"},
    },

    # ─── 6. リスクセンチメント（リスクオフ=円高） ──
    "リスクセンチメント": {
        "^VIX":  {"name": "VIX (恐怖指数)",      "jpy_impact": "strong", "weight": 5, "unit": ""},
        "^MOVE": {"name": "MOVE指数 (債券ボラ)", "jpy_impact": "strong", "weight": 3, "unit": ""},
        "^SKEW": {"name": "SKEW指数",            "jpy_impact": "strong", "weight": 2, "unit": ""},
    },

    # ─── 7. 株式市場（リスクオン/オフ判定） ─────────
    "株式市場": {
        "^GSPC":     {"name": "S&P 500",        "jpy_impact": "weak", "weight": 4, "unit": ""},
        "^IXIC":     {"name": "NASDAQ総合",     "jpy_impact": "weak", "weight": 3, "unit": ""},
        "^DJI":      {"name": "NYダウ",         "jpy_impact": "weak", "weight": 3, "unit": ""},
        "^N225":     {"name": "日経平均",       "jpy_impact": "weak", "weight": 4, "unit": "¥"},
        "^TPX":      {"name": "TOPIX",          "jpy_impact": "weak", "weight": 3, "unit": "¥"},
        "^HSI":      {"name": "ハンセン指数",   "jpy_impact": "weak", "weight": 2, "unit": ""},
        "000001.SS": {"name": "上海総合指数",   "jpy_impact": "weak", "weight": 2, "unit": "¥"},
    },

    # ─── 8. クロスレート ────────────────────────────
    "クロスレート（FX）": {
        "EURUSD=X": {"name": "EUR/USD",          "jpy_impact": "depends", "weight": 3, "unit": ""},
        "GBPUSD=X": {"name": "GBP/USD",          "jpy_impact": "depends", "weight": 2, "unit": ""},
        "AUDUSD=X": {"name": "AUD/USD",          "jpy_impact": "weak",    "weight": 3, "unit": ""},
        "NZDUSD=X": {"name": "NZD/USD",          "jpy_impact": "weak",    "weight": 2, "unit": ""},
        "USDCNH=X": {"name": "USD/CNH (人民元)", "jpy_impact": "weak",    "weight": 4, "unit": "¥"},
        "USDKRW=X": {"name": "USD/KRW (ウォン)", "jpy_impact": "weak",    "weight": 2, "unit": "₩"},
        "USDCHF=X": {"name": "USD/CHF (スイス)", "jpy_impact": "weak",    "weight": 2, "unit": ""},
    },

    # ─── 9. 暗号資産（リスク資産バロメーター） ──────
    "暗号資産": {
        "BTC-USD": {"name": "Bitcoin",  "jpy_impact": "weak", "weight": 3, "unit": "$"},
        "ETH-USD": {"name": "Ethereum", "jpy_impact": "weak", "weight": 2, "unit": "$"},
    },

    # ─── 10. 海運・輸送・実体経済 ───────────────────
    "海運・実体経済": {
        "FXI": {"name": "中国大型株ETF",         "jpy_impact": "weak", "weight": 2, "unit": "$"},
        "EEM": {"name": "新興国株ETF",           "jpy_impact": "weak", "weight": 2, "unit": "$"},
        "XLE": {"name": "エネルギーセクターETF", "jpy_impact": "weak", "weight": 2, "unit": "$"},
    },
}


# ════════════════════════════════════════════════
#  地政学・介入リスク（数値化されないがバイアスに加算）
# ════════════════════════════════════════════════

GEOPOLITICAL_RISKS = [
    {"region": "中東",     "type": "原油供給リスク",
     "impact": "weak",     "desc": "ホルムズ海峡封鎖懸念→原油急騰→円安要因"},
    {"region": "ウクライナ", "type": "エネルギー価格",
     "impact": "weak",     "desc": "天然ガス・小麦上昇→輸入インフレ→円安"},
    {"region": "台湾海峡", "type": "リスクオフ",
     "impact": "strong",   "desc": "緊急時はアジア圏通貨売り→安全資産の円買い"},
    {"region": "北朝鮮",   "type": "短期リスクオフ",
     "impact": "strong",   "desc": "ミサイル発射→一時的に円買い"},
    {"region": "米中貿易", "type": "貿易摩擦",
     "impact": "depends",  "desc": "報復関税→人民元安→円も連動売り or リスクオフ円買い"},
]


# ════════════════════════════════════════════════
#  日銀・FRB介入ライン（参考値）
# ════════════════════════════════════════════════

INTERVENTION_LEVELS = {
    "USDJPY": {
        "warning": 152.00,
        "intervention_likely": 155.00,
        "historical_intervention": [151.95, 155.20, 160.20],
        "note": "150円超で財務省口先介入、155円超で実弾介入の歴史",
    },
    "EURJPY": {
        "warning": 165.00,
        "intervention_likely": 170.00,
        "note": "クロス円も同時に介入対象となる",
    },
}


# ════════════════════════════════════════════════
#  ファクター取得＆分析エンジン
# ════════════════════════════════════════════════

def _fetch_factor(ticker: str) -> Optional[dict]:
    """単一ファクターの最新値・変動率・トレンドを取得"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period="3mo", interval="1d")
        if df is None or df.empty or len(df) < 5:
            return None

        close = df["Close"]
        current = close.iloc[-1]
        prev = close.iloc[-2]
        change = current - prev
        change_pct = (change / prev) * 100 if prev != 0 else 0

        def chg(periods):
            if len(close) > periods:
                return (current / close.iloc[-1 - periods] - 1) * 100
            return 0.0

        ch_5d = chg(5)
        ch_20d = chg(20)
        ch_60d = chg(60)

        ma5 = close.tail(5).mean()
        ma20 = close.tail(20).mean()
        if current > ma5 > ma20:
            trend = "上昇"
        elif current < ma5 < ma20:
            trend = "下降"
        else:
            trend = "横ばい"

        return {
            "current": round(float(current), 4),
            "change": round(float(change), 4),
            "change_pct": round(float(change_pct), 2),
            "change_5d": round(float(ch_5d), 2),
            "change_20d": round(float(ch_20d), 2),
            "change_60d": round(float(ch_60d), 2),
            "trend": trend,
        }
    except Exception:
        return None


def _calc_factor_bias(factor_meta: dict, factor_data: Optional[dict]) -> dict:
    """
    ファクターの現在の状態から円高/円安バイアススコアを算出

    Returns: {"bias", "score": -3〜+3, "label", "color"}
    """
    if factor_data is None:
        return {"bias": "neutral", "score": 0, "label": "データなし", "color": "#999"}

    impact = factor_meta["jpy_impact"]
    ch_5d = factor_data["change_5d"]
    weight = factor_meta["weight"]

    if impact == "weak":
        raw = ch_5d / 2.0
    elif impact == "strong":
        raw = -ch_5d / 2.0
    else:
        raw = 0

    score = max(-3, min(3, raw * (weight / 5)))

    if score > 1.0:
        bias = "weak"
        label = f"円安方向 (+{score:.1f})"
        color = "#D32030"
    elif score < -1.0:
        bias = "strong"
        label = f"円高方向 ({score:.1f})"
        color = "#1565C0"
    else:
        bias = "neutral"
        label = f"中立 ({score:+.1f})"
        color = "#888"

    return {
        "bias": bias,
        "score": round(score, 2),
        "label": label,
        "color": color,
        "weight": weight,
        "impact_type": impact,
    }


def analyze_all_factors() -> dict:
    """
    全ての円相場ファクターを取得＆分析し、総合判定を返す
    """
    categories = {}
    all_results = []

    for cat_name, factors in YEN_FACTORS.items():
        cat_results = []
        for ticker, meta in factors.items():
            data = _fetch_factor(ticker)
            bias_info = _calc_factor_bias(meta, data)

            entry = {
                "ticker": ticker,
                "name": meta["name"],
                "weight": meta["weight"],
                "unit": meta["unit"],
                "impact_type": meta["jpy_impact"],
                "data": data,
                "bias_info": bias_info,
            }
            cat_results.append(entry)
            all_results.append(entry)
        categories[cat_name] = cat_results

    total_score = sum(r["bias_info"]["score"] for r in all_results)
    weak_count = sum(1 for r in all_results if r["bias_info"]["bias"] == "weak")
    strong_count = sum(1 for r in all_results if r["bias_info"]["bias"] == "strong")
    neutral_count = sum(1 for r in all_results if r["bias_info"]["bias"] == "neutral")

    if total_score > 8:
        verdict = "円安バイアス"
        verdict_color = "#D32030"
        if total_score > 20:
            strength = "強"
        elif total_score > 14:
            strength = "中"
        else:
            strength = "弱"
    elif total_score < -8:
        verdict = "円高バイアス"
        verdict_color = "#1565C0"
        if total_score < -20:
            strength = "強"
        elif total_score < -14:
            strength = "中"
        else:
            strength = "弱"
    else:
        verdict = "中立（拮抗）"
        verdict_color = "#888"
        strength = "弱"

    weak_top = sorted(
        [r for r in all_results if r["bias_info"]["bias"] == "weak"],
        key=lambda r: r["bias_info"]["score"], reverse=True
    )[:5]
    strong_top = sorted(
        [r for r in all_results if r["bias_info"]["bias"] == "strong"],
        key=lambda r: r["bias_info"]["score"]
    )[:5]

    usdjpy_data = _fetch_factor("USDJPY=X")
    current_usdjpy = usdjpy_data["current"] if usdjpy_data else None

    return {
        "categories": categories,
        "summary": {
            "total_score": round(total_score, 1),
            "verdict": verdict,
            "verdict_strength": strength,
            "verdict_color": verdict_color,
            "weak_factors_count": weak_count,
            "strong_factors_count": strong_count,
            "neutral_factors_count": neutral_count,
            "top_weak_factors": weak_top,
            "top_strong_factors": strong_top,
        },
        "geopolitical": GEOPOLITICAL_RISKS,
        "intervention": INTERVENTION_LEVELS,
        "current_usdjpy": current_usdjpy,
        "analyzed_at": datetime.now().isoformat(),
    }


def get_intervention_warning(usdjpy: Optional[float]) -> Optional[dict]:
    """ドル円レベルから介入リスク警戒度を返す"""
    if usdjpy is None:
        return None
    levels = INTERVENTION_LEVELS["USDJPY"]
    if usdjpy >= levels["intervention_likely"]:
        return {
            "level": "高",
            "color": "#D32030",
            "message": f"⚠ {levels['intervention_likely']}円超 → 実弾介入の可能性極めて高い",
            "advice": "急激な円高への巻き戻しに注意",
        }
    elif usdjpy >= levels["warning"]:
        return {
            "level": "中",
            "color": "#FDB813",
            "message": f"⚠ {levels['warning']}円超 → 財務省・口先介入リスク",
            "advice": "要人発言・介入観測報道に警戒",
        }
    else:
        return {
            "level": "低",
            "color": "#1565C0",
            "message": f"介入水準（{levels['warning']}円）まで余裕あり",
            "advice": "—",
        }


def calc_us_jp_yield_spread() -> Optional[dict]:
    """米日金利差（10年債）を算出 - 円相場との相関が強い"""
    us10y = _fetch_factor("^TNX")
    if us10y is None:
        return None
    # 日本の10年債はyfinanceで取れないため、目安として0.7%（2025年想定）
    jp10y_proxy = 0.7
    spread = us10y["current"] - jp10y_proxy
    return {
        "us10y": us10y["current"],
        "jp10y_estimate": jp10y_proxy,
        "spread": round(spread, 2),
        "spread_5d_change": round(us10y["change_5d"], 2),
        "interpretation": (
            "金利差拡大 → 円安方向" if us10y["change_5d"] > 0
            else "金利差縮小 → 円高方向"
        ),
    }


def format_yen_analysis_report(analysis: dict) -> str:
    """analyze_all_factors の結果を日本語レポートに整形"""
    L = []
    s = analysis["summary"]
    L.append("╔══════════════════════════════════════════════╗")
    L.append("║   円相場 総合ファクター分析                    ║")
    L.append("╚══════════════════════════════════════════════╝")
    L.append(f" 分析日時        : {analysis['analyzed_at'][:19]}")
    L.append(f" 現在のUSD/JPY   : {analysis.get('current_usdjpy', '—')}")
    L.append(f" 総合スコア      : {s['total_score']:+.1f}")
    L.append(f" 判定            : {s['verdict']}（{s['verdict_strength']}）")
    L.append(f"   ├ 円安要因    : {s['weak_factors_count']} 個")
    L.append(f"   ├ 円高要因    : {s['strong_factors_count']} 個")
    L.append(f"   └ 中立        : {s['neutral_factors_count']} 個")
    L.append("───────────────────────────────────────────────")
    L.append(" 【円安方向に寄与 TOP5】")
    for i, r in enumerate(s["top_weak_factors"], 1):
        score = r["bias_info"]["score"]
        L.append(f"   {i}. {r['name']:<22} {score:+.2f}")
    L.append("")
    L.append(" 【円高方向に寄与 TOP5】")
    for i, r in enumerate(s["top_strong_factors"], 1):
        score = r["bias_info"]["score"]
        L.append(f"   {i}. {r['name']:<22} {score:+.2f}")
    L.append("───────────────────────────────────────────────")
    warn = get_intervention_warning(analysis.get("current_usdjpy"))
    if warn:
        L.append(f" 介入リスク      : {warn['level']} — {warn['message']}")
    L.append("═══════════════════════════════════════════════")
    return "\n".join(L)


if __name__ == "__main__":
    print("円相場ファクター分析中…（全ティッカー取得に30秒ほどかかります）")
    analysis = analyze_all_factors()
    print(format_yen_analysis_report(analysis))
