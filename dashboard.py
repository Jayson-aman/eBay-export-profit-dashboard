"""
dashboard.py — eBay 輸出 利益判定 Web ダッシュボード

使い方:
    streamlit run dashboard.py

機能:
  1. 単品判定 — 商品情報を入力して利益・ROI・最低販売価格を即時計算（JAN/バーコードから仕入れ候補取得可）
  2. CSV一括判定 — CSVアップロードで複数商品を一気に判定
  3. 為替シナリオ — USD/JPY変動による利益シミュレーション
  4. 円相場バイアス — 30+ファクターから総合判定
  5. 仕入れ検索 — 楽天/Yahoo!S/Yahoo!オク から自動で仕入れ候補を取得 → 利益判定
  6. 全自動リサーチ — eBay相場で売値を推定 → 楽天/Yahoo!Sと突合して利益ランキング
  7. 購買心理・先読み — 季節・心理タグ・半球／気候＋**イベント別出品前倒し**（クリスマス・入学等）
"""

from __future__ import annotations

import io
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from ebay_research import CONDITIONS as EBAY_CONDITIONS
from ebay_research import marketplace_for_destination
from event_calendar import (
    build_listing_calendar,
    format_listing_calendar_report,
    upcoming_actions,
)
from psychology_intent import (
    PSYCH_DRIVERS,
    merge_categories_for_ui,
    compute_purchase_intent,
    format_intent_report,
)
from profit_tools import (
    SOURCES, CATEGORIES, DESTINATION_ZONE,
    BUILDING_CHEMICAL_EXPORT_NOTES,
    EXPORT_OMITTED_PRODUCTS_NOTE,
    calc_unified, calc_unified_with_bias, format_unified_report,
    scenario_analysis, batch_calc_from_csv, generate_sample_csv,
    estimate_shipping, estimate_tariff,
    _fetch_usdjpy,
)
from ui_modern import apply_modern_ui, render_modern_hero
from barcode_jan import normalize_product_barcode, search_rakuten_yahoo_shopping
from amasearch import (
    AMASEARCH_APP_STORE_SEARCH,
    AMASEARCH_GOOGLE_PLAY,
    AMASEARCH_OFFICIAL,
    amazon_co_jp_search_url,
)


def merged_category_list(include_placeholder: bool = True) -> list[str]:
    m = merge_categories_for_ui(CATEGORIES)
    keys = sorted(m.categories_display.keys())
    return (["(選択)"] + keys) if include_placeholder else keys


def default_category_index(include_placeholder: bool) -> int:
    lst = merged_category_list(include_placeholder)
    if "骨董品・陶磁器" in lst:
        return lst.index("骨董品・陶磁器")
    return 0 if not include_placeholder else 1


# ════════════════════════════════════════════════
#  ページ設定
# ════════════════════════════════════════════════

st.set_page_config(
    page_title="eBay 輸出 利益判定",
    page_icon="💴",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_modern_ui()


# ════════════════════════════════════════════════
#  共通ユーティリティ
# ════════════════════════════════════════════════

@st.cache_data(ttl=300)  # 5分キャッシュ
def get_usdjpy_cached() -> float | None:
    """USD/JPYを5分キャッシュで取得"""
    return _fetch_usdjpy()


@st.cache_data(ttl=600)  # 10分キャッシュ
def get_yen_analysis_cached() -> dict | None:
    """円相場分析をキャッシュ付きで取得"""
    try:
        from yen_factors import analyze_all_factors
        return analyze_all_factors()
    except Exception as e:
        st.error(f"円相場分析失敗: {e}")
        return None


# ヒーロー・タブで共通利用する USD/JPY（1回取得）
usdjpy_live = get_usdjpy_cached()


def judge_color(judge: str) -> str:
    return {"GO": "#22c55e", "HOLD": "#f59e0b", "STOP": "#ef4444"}.get(judge, "#64748b")


def judge_emoji(judge: str) -> str:
    return {"GO": "✅", "HOLD": "⚠️", "STOP": "⛔"}.get(judge, "")


# ════════════════════════════════════════════════
#  サイドバー：共通設定
# ════════════════════════════════════════════════

with st.sidebar:
    st.title("💴 eBay輸出 利益判定")
    st.caption("送料・関税・為替まで自動計算")

    st.divider()
    st.subheader("📊 現在の為替")
    if usdjpy_live:
        st.metric("USD/JPY", f"{usdjpy_live:.2f}",
                  help="yfinance から5分間隔で取得")
    else:
        st.warning("為替取得失敗")

    st.divider()
    st.subheader("⚙️ 共通設定")
    default_dest = st.selectbox(
        "デフォルト仕向地",
        sorted(set(DESTINATION_ZONE.keys()), key=lambda x: DESTINATION_ZONE[x]),
        index=list(DESTINATION_ZONE.keys()).index("アメリカ"),
    )
    default_target_roi = st.slider("目標ROI (%)", 10, 100, 30, 5)
    default_method = st.selectbox("デフォルト発送方法",
                                  ["EMS", "DHL", "SAL", "eパケット"])

    st.divider()
    st.subheader("🔑 APIキー")
    with st.expander("仕入れ元API（楽天 / Yahoo!S）"):
        rakuten_app_id = st.text_input(
            "楽天APP_ID",
            value=os.environ.get("RAKUTEN_APP_ID", ""),
            type="password",
            help="https://webservice.rakuten.co.jp/ で無料取得",
        )
        yahoo_app_id = st.text_input(
            "Yahoo!Client ID",
            value=os.environ.get("YAHOO_APP_ID", ""),
            type="password",
            help="https://e.developer.yahoo.co.jp/ で無料取得",
        )
        if rakuten_app_id:
            os.environ["RAKUTEN_APP_ID"] = rakuten_app_id
        if yahoo_app_id:
            os.environ["YAHOO_APP_ID"] = yahoo_app_id

    with st.expander("eBay相場API（売値リサーチ）"):
        ebay_client_id = st.text_input(
            "eBay App ID（Client ID）",
            value=os.environ.get("EBAY_CLIENT_ID", ""),
            type="password",
            help="https://developer.ebay.com/ でProduction keyを取得",
        )
        ebay_client_secret = st.text_input(
            "eBay Cert ID（Client Secret）",
            value=os.environ.get("EBAY_CLIENT_SECRET", ""),
            type="password",
        )
        if ebay_client_id:
            os.environ["EBAY_CLIENT_ID"] = ebay_client_id
        if ebay_client_secret:
            os.environ["EBAY_CLIENT_SECRET"] = ebay_client_secret

    with st.expander("📦 防水・塗料・シーリング等の輸出（注意）"):
        st.text(BUILDING_CHEMICAL_EXPORT_NOTES)

    with st.expander("🚫 例示から省く品目（充電器・汎用USB等）"):
        st.text(EXPORT_OMITTED_PRODUCTS_NOTE)

    with st.expander("🛒 アマサーチ（Amazon 相場リサーチ）"):
        st.caption(
            "店舗せどり向け公式アプリ。**本アプリと API 連携はありません**。"
            "バーコードはスマホでアマサーチを開き、同じ JAN を読み取ってください。"
        )
        _a1, _a2, _a3 = st.columns(3)
        with _a1:
            st.link_button("公式サイト", AMASEARCH_OFFICIAL, use_container_width=True)
        with _a2:
            st.link_button("Google Play", AMASEARCH_GOOGLE_PLAY, use_container_width=True)
        with _a3:
            st.link_button("App Store", AMASEARCH_APP_STORE_SEARCH, use_container_width=True)

    with st.expander("📱 携帯のキャリア回線から開く", expanded=False):
        st.markdown(
            "家の Wi-Fi 外（4G/5G）から見るには、PC 上で **トンネル**が必要です。\n\n"
            "プロジェクト内の `start_external_access.sh` をターミナルで実行し、"
            "表示された **https://…trycloudflare.com** を携帯ブラウザに入れてください。 "
            "事前に `brew install cloudflared` などで **cloudflared** を入れてください。 "
            "URL は**認証なし**のため知る人は誰でも開けます。終わったらスクリプトを **Ctrl+C** で止めてください。",
        )

    st.divider()
    st.caption(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ════════════════════════════════════════════════
#  メイン: ヒーロー
# ════════════════════════════════════════════════

render_modern_hero(usdjpy_live)

# ════════════════════════════════════════════════
#  メインタブ
# ════════════════════════════════════════════════

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔍 単品判定",
    "📁 CSV一括判定",
    "📈 為替シナリオ",
    "🌐 円相場バイアス",
    "🛒 仕入れ検索",
    "🎯 全自動リサーチ",
    "🧠 購買心理・先読み",
])


# ════════════════════════════════════════════════
#  Tab1: 単品判定
# ════════════════════════════════════════════════

with tab1:
    st.header("🔍 単品 利益判定")

    if "t1_pname" not in st.session_state:
        st.session_state.t1_pname = "九谷焼 赤絵金彩 花瓶 明治期 共箱付"
    if "t1_cost" not in st.session_state:
        st.session_state.t1_cost = 12000

    col_form, col_result = st.columns([1, 1.2])

    with col_form:
        st.subheader("商品情報を入力")

        with st.expander("📷 JAN / バーコードで仕入れ候補を探す", expanded=False):
            st.caption(
                "**8〜13桁**（EAN-8 / UPC / JAN・EAN-13）を数字で入力。楽天市場・Yahoo!ショッピングの"
                "**キーワード検索**（タイトル等に同じ数字の列挙がある商品向け）です。ヒットしない商品もあり、"
                "0件のときは手入力に切り替えてください。"
            )
            st.text_input(
                "JAN / バーコード",
                placeholder="例: 4901234567890（EAN-13）",
                key="t1_bc_raw",
            )
            st.markdown("###### アマサーチ・Amazon.co.jp（外部リンク）")
            st.caption(
                "アマサーチはスマホアプリ（公式）。"
                "ここからはブラウザで公式・ストア・国内 Amazon 検索のみ開きます。"
            )
            _al1, _al2, _al3 = st.columns(3)
            with _al1:
                st.link_button("アマサーチ公式", AMASEARCH_OFFICIAL, use_container_width=True)
            with _al2:
                st.link_button("Google Play", AMASEARCH_GOOGLE_PLAY, use_container_width=True)
            with _al3:
                st.link_button("App Store", AMASEARCH_APP_STORE_SEARCH, use_container_width=True)
            _amz_q = (st.session_state.get("t1_bc_raw") or "").strip()
            if _amz_q:
                st.link_button(
                    "Amazon.co.jp で上欄を検索",
                    amazon_co_jp_search_url(_amz_q),
                    use_container_width=True,
                )
            st.divider()

            if st.button("店舗を検索", key="t1_bc_search", type="secondary"):
                _code, _bc_err = normalize_product_barcode(
                    st.session_state.get("t1_bc_raw", "") or "",
                )
                if _bc_err:
                    st.error(_bc_err)
                else:
                    with st.spinner("楽天・Yahoo!で検索中…"):
                        _rows_bc, _src_errs = search_rakuten_yahoo_shopping(_code)
                    st.session_state.t1_bc_hits = _rows_bc
                    st.session_state.t1_bc_last_code = _code
                    for _msg in _src_errs:
                        st.warning(_msg)
            _hits_bc = st.session_state.get("t1_bc_hits")
            if _hits_bc is not None and len(_hits_bc) == 0:
                st.info("0件でした。商品名の手入力、または「🛒 仕入れ検索」タブを利用してください。")
            elif _hits_bc:
                st.caption(
                    f"キーワード: `{st.session_state.get('t1_bc_last_code', '')}` — "
                    f"{len(_hits_bc)} 件"
                )

                def _t1_row_label(i: int) -> str:
                    h = _hits_bc[i]
                    cj = int(h.get("cost_jpy", 0) or 0)
                    nm = (h.get("product_name", "") or "")[:72]
                    return f"[{h.get('source', '')}] ¥{cj:,} — {nm}"

                _ix = st.selectbox(
                    "候補",
                    list(range(len(_hits_bc))),
                    format_func=_t1_row_label,
                    key="t1_bc_pick",
                )
                if st.button("選択行を「商品名」「仕入れ値 (円)」に反映", key="t1_bc_apply"):
                    _h = _hits_bc[int(_ix)]
                    st.session_state.t1_pname = _h.get("product_name", "") or st.session_state.t1_pname
                    st.session_state.t1_cost = int(_h.get("cost_jpy", 0) or 0)
                    st.toast("フォームの商品名と仕入れ値を更新しました。計算は下のボタンで。", icon="📷")
                    st.success("反映しました。下の「💡 利益を計算する」で再計算できます。")

        with st.form("single_calc"):
            product_name = st.text_input("商品名", key="t1_pname")
            sku = st.text_input("SKU（任意）", value="ANT-KUT-001")

            cc1, cc2 = st.columns(2)
            with cc1:
                _cl = merged_category_list(True)
                category = st.selectbox("カテゴリ",
                                        _cl,
                                        index=default_category_index(True))
            with cc2:
                source_keys = ["(任意)"] + list(SOURCES.keys())
                source_sel = st.selectbox(
                    "仕入れ先",
                    source_keys,
                    index=source_keys.index("yahoo_auction"),
                    format_func=lambda k: SOURCES[k]["name"] if k in SOURCES else k,
                )
                source = "" if source_sel == "(任意)" else source_sel

            st.markdown("---")

            cp1, cp2 = st.columns(2)
            with cp1:
                cost_jpy = st.number_input("仕入れ値 (円)",
                                           min_value=0, key="t1_cost", step=100)
                weight_g = st.number_input("重量 (g)",
                                           min_value=1, value=1800, step=50)
            with cp2:
                sell_price_usd = st.number_input("想定販売価格 ($)",
                                                 min_value=0.0, value=280.0, step=5.0)
                packing = st.number_input("梱包費 (円)",
                                          min_value=0, value=300, step=50)

            st.markdown("---")

            cd1, cd2, cd3 = st.columns(3)
            with cd1:
                destination = st.selectbox(
                    "仕向地",
                    sorted(set(DESTINATION_ZONE.keys()),
                           key=lambda x: DESTINATION_ZONE[x]),
                    index=list(DESTINATION_ZONE.keys()).index(default_dest),
                )
            with cd2:
                shipping_method = st.selectbox(
                    "発送方法",
                    ["EMS", "DHL", "SAL", "eパケット"],
                    index=["EMS", "DHL", "SAL", "eパケット"].index(default_method),
                )
            with cd3:
                target_roi = st.number_input("目標ROI (%)",
                                             min_value=0, max_value=200,
                                             value=default_target_roi, step=5)

            seller_pays = st.checkbox(
                "DDP: セラーが関税を負担する（通常オフ）",
                value=False,
                help="オンにすると関税・VATも自動でコストに加算",
            )
            include_bias = st.checkbox(
                "🌐 円相場バイアス分析も含める（+20秒）",
                value=False,
                help="30以上のファクターから円高/円安バイアスを判定",
            )
            include_psych = st.checkbox(
                "🧠 購買心理・先読みスコアを表示",
                value=False,
                help="季節・行事・カテゴリの心理タグから需要の傾きを推定（ヒューリスティクス）",
            )
            psych_mood = st.slider(
                "社会ムード（体感・ニュースの空気）",
                -1.0,
                1.0,
                0.0,
                0.1,
                help="不安・節約寄り(-) / 楽観・ご褒美寄り(+)。購買心理表示をオンにしたときのみ結果に反映",
            )

            submit = st.form_submit_button("💡 利益を計算する",
                                           type="primary", use_container_width=True)

    with col_result:
        if submit:
            cat = category if category != "(選択)" else ""
            with st.spinner("計算中…"):
                if include_bias:
                    result = calc_unified_with_bias(
                        cost_jpy=cost_jpy,
                        sell_price_usd=sell_price_usd,
                        weight_g=weight_g,
                        category=cat,
                        destination=destination,
                        product_name=product_name,
                        sku=sku,
                        source=source,
                        shipping_method=shipping_method,
                        seller_pays_tariff=seller_pays,
                        packing_cost_jpy=packing,
                        target_roi=target_roi,
                        yen_analysis=get_yen_analysis_cached(),
                    )
                else:
                    result = calc_unified(
                        cost_jpy=cost_jpy,
                        sell_price_usd=sell_price_usd,
                        weight_g=weight_g,
                        category=cat,
                        destination=destination,
                        product_name=product_name,
                        sku=sku,
                        source=source,
                        shipping_method=shipping_method,
                        seller_pays_tariff=seller_pays,
                        packing_cost_jpy=packing,
                        target_roi=target_roi,
                    )

            st.subheader("判定結果")
            j = result["judge"]
            st.markdown(
                f"<div style='padding:16px;border-radius:8px;"
                f"background:{judge_color(j)};color:white;text-align:center;"
                f"font-size:28px;font-weight:bold;'>"
                f"{judge_emoji(j)} {j} — "
                f"{'仕入れ推奨' if j == 'GO' else '要検討' if j == 'HOLD' else '見送り'}"
                f"</div>",
                unsafe_allow_html=True,
            )

            # メトリクス4枚
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("純利益", f"¥{result['profit_jpy']:,}")
            with m2:
                st.metric("利益率", f"{result['margin_pct']}%")
            with m3:
                st.metric("ROI", f"{result['roi_pct']}%",
                          delta=f"目標{target_roi}%比 "
                                f"{result['roi_pct'] - target_roi:+.1f}pt")
            with m4:
                st.metric("最低販売価格",
                          f"${result['min_sell_price_usd']:.2f}",
                          delta=f"現在価格 {result['price_vs_minimum']:+.2f}")

            # コスト内訳 円グラフ
            st.markdown("### コスト内訳")
            cost_breakdown = {
                "仕入れ値": result["cost_total_jpy"]
                          - result["shipping_cost_jpy"]
                          - result["packing_cost_jpy"]
                          - result["tariff_cost_jpy"],
                "国際送料": result["shipping_cost_jpy"],
                "梱包": result["packing_cost_jpy"],
            }
            if result["tariff_cost_jpy"] > 0:
                cost_breakdown["関税(DDP)"] = result["tariff_cost_jpy"]

            fig = go.Figure(data=[go.Pie(
                labels=list(cost_breakdown.keys()),
                values=list(cost_breakdown.values()),
                hole=0.4,
                textinfo="label+percent",
            )])
            fig.update_layout(
                height=300,
                margin=dict(t=20, b=20, l=20, r=20),
                showlegend=True,
            )
            st.plotly_chart(fig, use_container_width=True)

            # 為替タイミング
            st.info(f"🕐 **為替タイミング**: {result['timing']}")
            if result.get("intervention_risk"):
                ir = result["intervention_risk"]
                level_color = {"高": "error", "中": "warning", "低": "info"}[ir["level"]]
                getattr(st, level_color)(f"**介入リスク {ir['level']}** — {ir['message']}")

            # 円相場バイアス（あれば）
            if result.get("yen_bias"):
                b = result["yen_bias"]
                with st.expander("🌐 円相場バイアス詳細", expanded=True):
                    bc1, bc2, bc3 = st.columns(3)
                    bc1.metric("総合スコア", f"{b['total_score']:+.1f}")
                    bc2.metric("判定", f"{b['verdict']}（{b['strength']}）")
                    bc3.metric("要因内訳",
                               f"円安{b['weak_count']} / 円高{b['strong_count']}")
                    st.write(f"**アクション**: {result.get('action_advice', '')}")
                    if b["top_weak_factors"]:
                        st.write(f"**円安要因TOP3**: {', '.join(b['top_weak_factors'])}")
                    if b["top_strong_factors"]:
                        st.write(f"**円高要因TOP3**: {', '.join(b['top_strong_factors'])}")

            # テキストレポート
            with st.expander("📄 テキストレポート全文"):
                st.code(format_unified_report(result), language="text")

            if include_psych and cat:
                with st.expander("🧠 購買心理・先読み（参考）", expanded=True):
                    pi = compute_purchase_intent(
                        cat,
                        destination,
                        date.today(),
                        social_mood=psych_mood,
                    )
                    pm1, pm2, pm3, pm4 = st.columns(4)
                    pm1.metric("意欲スコア", f"{pi['intent_score']}/100")
                    pm2.metric("需要補正（参考）", f"×{pi['intent_multiplier']}")
                    pm3.metric("気候ブレンド後", f"×{pi['intent_multiplier_climate_blended']}")
                    pm4.metric("仕向け補正", f"×{pi['destination_multiplier']}")
                    st.caption(pi["forward_horizon_note"])
                    cc = pi.get("climate_context") or {}
                    if cc:
                        st.markdown("##### 🌍 現地の季節・気候・ニーズ")
                        st.write(
                            f"**{cc.get('climate_label_ja', '—')}** ・ "
                            f"**{cc.get('local_season_ja', '—')}** "
                            f"（半球: {cc.get('hemisphere', '—')}）"
                        )
                        st.caption(cc.get("hemisphere_note", ""))
                        for n in cc.get("need_insights_ja") or []:
                            st.markdown(f"- {n}")
                        st.caption(
                            f"カテゴリ季節相性: ×{cc.get('category_fit_multiplier', 1)} "
                            f"— {cc.get('category_fit_note', '')}"
                        )
                    with st.expander("心理タグ内訳"):
                        for row in pi["factors"]:
                            st.write(
                                f"**{row['label']}** (`{row['tag']}`) "
                                f"寄与 {row['contribution']:+.4f}"
                            )
                    st.code(format_intent_report(pi), language="text")
        else:
            st.info("👈 左のフォームに情報を入力して「利益を計算する」を押してください")


# ════════════════════════════════════════════════
#  Tab2: CSV一括判定
# ════════════════════════════════════════════════

with tab2:
    st.header("📁 CSV 一括判定")

    col_upload, col_sample = st.columns([2, 1])

    with col_upload:
        uploaded = st.file_uploader(
            "商品リストCSVをアップロード",
            type=["csv"],
            help="列名: 商品名, SKU, カテゴリ, 仕入れ先, 仕入れ値, 想定販売価格, "
                 "重量g, 仕向地, 発送方法, 関税負担, 目標ROI",
        )
    with col_sample:
        st.markdown("##### サンプルCSVが欲しい場合")
        if st.button("📥 サンプルCSVを生成", use_container_width=True):
            path = generate_sample_csv("sample_products.csv")
            with open(path, "rb") as f:
                st.download_button(
                    "⬇ sample_products.csv をダウンロード",
                    data=f.read(),
                    file_name="sample_products.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

    if uploaded:
        # 一時ファイルに保存してバッチ実行
        with open("_uploaded.csv", "wb") as f:
            f.write(uploaded.read())

        with st.spinner(f"{uploaded.name} を処理中…"):
            summary = batch_calc_from_csv(
                input_csv="_uploaded.csv",
                output_csv="_result_all.csv",
                go_only_csv="_result_go.csv",
                default_destination=default_dest,
                default_target_roi=default_target_roi,
                default_shipping_method=default_method,
                usdjpy=usdjpy_live,
            )

        # サマリー
        st.success(f"✅ {summary['total']} 件処理完了")
        st.toast(f"{summary['total']} 件の一括判定が完了しました", icon="✅")

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("総件数", summary["total"])
        sm2.metric("✅ GO", summary["go"],
                   delta=f"{summary['go']/summary['total']*100:.0f}%")
        sm3.metric("⚠️ HOLD", summary["hold"])
        sm4.metric("⛔ STOP", summary["stop"])

        # エラー
        if summary["errors"]:
            with st.expander(f"⚠️ エラー {len(summary['errors'])} 件"):
                for e in summary["errors"]:
                    st.write(f"行{e['row']}: {e['error']}")

        # 結果テーブル
        df_all = pd.DataFrame(summary["results"])
        display_cols = [
            "product_name", "category", "destination", "cost_total_jpy",
            "revenue_usd", "profit_jpy", "roi_pct",
            "min_sell_price_usd", "judge",
        ]
        df_show = df_all[display_cols].copy()
        df_show.columns = ["商品名", "カテゴリ", "仕向地", "総コスト",
                           "売上USD", "純利益", "ROI%",
                           "最低販売価格$", "判定"]

        # 色付け
        def highlight_judge(v):
            color = judge_color(v)
            return f"background-color: {color}; color: white; font-weight: bold"

        styled = df_show.style.map(highlight_judge, subset=["判定"])
        st.dataframe(styled, use_container_width=True, height=400)

        # ダウンロードボタン
        dl1, dl2 = st.columns(2)
        with dl1:
            with open("_result_all.csv", "rb") as f:
                st.download_button(
                    "⬇ 全結果CSV",
                    data=f.read(),
                    file_name=f"results_all_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
        with dl2:
            with open("_result_go.csv", "rb") as f:
                st.download_button(
                    "⬇ GO商品のみCSV",
                    data=f.read(),
                    file_name=f"results_go_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        # TOP3
        st.markdown("### 🏆 利益率 TOP3")
        for i, r in enumerate(summary["best_top3"], 1):
            with st.container(border=True):
                cc = st.columns([3, 1, 1, 1])
                cc[0].markdown(f"**{i}位** {r['product_name']}")
                cc[1].metric("ROI", f"{r['roi_pct']}%")
                cc[2].metric("利益", f"¥{r['profit_jpy']:,}")
                cc[3].markdown(
                    f"<div style='padding:8px;border-radius:6px;"
                    f"background:{judge_color(r['judge'])};color:white;"
                    f"text-align:center;font-weight:bold;'>{r['judge']}</div>",
                    unsafe_allow_html=True,
                )

        # ROI分布グラフ
        st.markdown("### 📊 ROI分布")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=[r["product_name"][:20] for r in summary["results"]],
            y=[r["roi_pct"] for r in summary["results"]],
            marker_color=[judge_color(r["judge"]) for r in summary["results"]],
            text=[f"{r['roi_pct']}%" for r in summary["results"]],
            textposition="outside",
        ))
        fig.add_hline(y=default_target_roi, line_dash="dash", line_color="gray",
                      annotation_text=f"目標 {default_target_roi}%")
        fig.update_layout(
            xaxis_title="", yaxis_title="ROI (%)",
            height=400, margin=dict(t=20, b=120),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("👆 CSVファイルをアップロードするか、サンプルCSVをダウンロードして試してください")


# ════════════════════════════════════════════════
#  Tab3: 為替シナリオ
# ════════════════════════════════════════════════

with tab3:
    st.header("📈 為替シナリオ分析")
    st.caption("USD/JPYが動いたときに利益がどう変わるかを可視化")

    with st.form("scenario_form"):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            s_product = st.text_input("商品名", "九谷焼 花瓶")
            _scl = merged_category_list(False)
            s_category = st.selectbox("カテゴリ", _scl,
                                      index=default_category_index(False),
                                      key="sc_cat")
        with sc2:
            s_cost = st.number_input("仕入れ値 (円)", 0, value=12000, step=100)
            s_sell = st.number_input("販売価格 ($)", 0.0, value=280.0, step=5.0)
        with sc3:
            s_weight = st.number_input("重量 (g)", 1, value=1800, step=50)
            s_dest = st.selectbox("仕向地",
                                  sorted(set(DESTINATION_ZONE.keys()),
                                         key=lambda x: DESTINATION_ZONE[x]),
                                  index=list(DESTINATION_ZONE.keys()).index(default_dest),
                                  key="sc_dest")

        s_target_roi = st.slider("目標ROI (%)", 10, 100, default_target_roi, 5,
                                 key="sc_roi")
        s_submit = st.form_submit_button("📊 シナリオ分析を実行",
                                          type="primary", use_container_width=True)

    if s_submit:
        with st.spinner("計算中…"):
            r = scenario_analysis(
                cost_jpy=s_cost,
                sell_price_usd=s_sell,
                weight_g=s_weight,
                category=s_category,
                destination=s_dest,
                product_name=s_product,
                target_roi=s_target_roi,
                current_usdjpy=usdjpy_live,
            )

        st.subheader("シナリオ結果")
        k1, k2, k3 = st.columns(3)
        k1.metric("現在USD/JPY", f"{r['current_usdjpy']:.2f}")
        if r["breakeven_usdjpy"]:
            k2.metric("損益分岐", f"{r['breakeven_usdjpy']:.2f}",
                      delta=f"余裕 {r['current_usdjpy'] - r['breakeven_usdjpy']:+.2f} 円")
        if r["target_roi_usdjpy"]:
            k3.metric(f"ROI{s_target_roi}%達成ライン",
                      f"{r['target_roi_usdjpy']:.2f}",
                      delta=f"{r['current_usdjpy'] - r['target_roi_usdjpy']:+.2f} 円")

        # グラフ
        df_s = pd.DataFrame(r["scenarios"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_s["usdjpy"], y=df_s["profit_jpy"],
            mode="lines+markers+text",
            text=[f"¥{v:,}" for v in df_s["profit_jpy"]],
            textposition="top center",
            marker=dict(
                size=12,
                color=[judge_color(j) for j in df_s["judge"]],
                line=dict(width=2, color="white"),
            ),
            line=dict(width=3, color="#6366f1"),
        ))
        if r["breakeven_usdjpy"]:
            fig.add_hline(y=0, line_dash="dash", line_color="red",
                          annotation_text="損益分岐(¥0)")
        fig.add_vline(x=r["current_usdjpy"], line_dash="dot",
                      line_color="gray", annotation_text="現在")
        fig.update_layout(
            title="USD/JPY と 利益(¥)",
            xaxis_title="USD/JPY", yaxis_title="純利益 (円)",
            height=450, margin=dict(t=50, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        # テーブル
        df_show = df_s[["usdjpy", "label", "profit_jpy", "roi_pct", "judge"]].copy()
        df_show.columns = ["USD/JPY", "シナリオ", "利益(¥)", "ROI(%)", "判定"]

        def highlight_judge(v):
            return f"background-color: {judge_color(v)}; color: white; font-weight: bold"

        styled = df_show.style.map(highlight_judge, subset=["判定"])
        st.dataframe(styled, use_container_width=True)


# ════════════════════════════════════════════════
#  Tab4: 円相場バイアス
# ════════════════════════════════════════════════

with tab4:
    st.header("🌐 円相場 総合バイアス分析")
    st.caption("金利・資源・株式・VIX・地政学 — 30+ファクターから円高/円安を判定")

    if st.button("🔄 最新データで再分析する（30〜60秒）",
                 type="primary"):
        get_yen_analysis_cached.clear()  # キャッシュクリア

    analysis = get_yen_analysis_cached()
    if analysis:
        s = analysis["summary"]

        # ゲージ
        verdict_color = {
            "円安バイアス": "#D32030",
            "円高バイアス": "#1565C0",
            "中立（拮抗）": "#888888",
        }.get(s["verdict"], "#888888")

        st.markdown(
            f"<div style='padding:20px;border-radius:10px;"
            f"background:{verdict_color};color:white;text-align:center;"
            f"font-size:32px;font-weight:bold;'>"
            f"{s['verdict']} — {s['verdict_strength']}"
            f"<br><span style='font-size:18px;'>総合スコア {s['total_score']:+.1f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.write("")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("現在USD/JPY", f"{analysis.get('current_usdjpy', 0):.2f}")
        m2.metric("円安要因", f"{s['weak_factors_count']} 個")
        m3.metric("円高要因", f"{s['strong_factors_count']} 個")
        m4.metric("中立", f"{s['neutral_factors_count']} 個")

        # TOP5
        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown("### 📈 円安方向 TOP5")
            for i, f in enumerate(s["top_weak_factors"], 1):
                st.write(f"{i}. **{f['name']}** "
                         f"`{f['bias_info']['score']:+.2f}` "
                         f"({f['impact_type']})")
        with tc2:
            st.markdown("### 📉 円高方向 TOP5")
            for i, f in enumerate(s["top_strong_factors"], 1):
                st.write(f"{i}. **{f['name']}** "
                         f"`{f['bias_info']['score']:+.2f}` "
                         f"({f['impact_type']})")

        # カテゴリ別スコア
        st.markdown("### 📊 カテゴリ別スコア")
        cat_scores = {}
        for cat_name, factors in analysis["categories"].items():
            total = sum(f["bias_info"]["score"] for f in factors)
            cat_scores[cat_name] = round(total, 2)

        df_cat = pd.DataFrame([
            {"カテゴリ": k, "スコア": v} for k, v in cat_scores.items()
        ]).sort_values("スコア")

        fig = go.Figure(go.Bar(
            x=df_cat["スコア"],
            y=df_cat["カテゴリ"],
            orientation="h",
            marker_color=["#D32030" if v > 0 else "#1565C0" for v in df_cat["スコア"]],
            text=[f"{v:+.2f}" for v in df_cat["スコア"]],
            textposition="outside",
        ))
        fig.update_layout(
            xaxis_title="スコア (+円安 / −円高)",
            height=400, margin=dict(t=20, b=40, l=180),
        )
        st.plotly_chart(fig, use_container_width=True)

        # 地政学リスク
        with st.expander("🌍 地政学リスク"):
            for risk in analysis["geopolitical"]:
                impact_color = {"weak": "🔴 円安", "strong": "🔵 円高",
                                "depends": "⚪ 状況依存"}.get(risk["impact"], "")
                st.write(f"**{risk['region']}**（{risk['type']}）{impact_color}")
                st.caption(risk["desc"])

        # 詳細テーブル
        with st.expander("📋 全ファクター詳細"):
            rows = []
            for cat_name, factors in analysis["categories"].items():
                for f in factors:
                    if f["data"]:
                        rows.append({
                            "カテゴリ": cat_name,
                            "ファクター": f["name"],
                            "現在値": f["data"]["current"],
                            "5日変動%": f["data"]["change_5d"],
                            "20日変動%": f["data"]["change_20d"],
                            "トレンド": f["data"]["trend"],
                            "影響": f["impact_type"],
                            "スコア": f["bias_info"]["score"],
                        })
            df_factors = pd.DataFrame(rows)
            st.dataframe(df_factors, use_container_width=True, height=500)
    else:
        st.warning("データ取得に失敗しました。ネットワーク接続を確認してください。")


# ════════════════════════════════════════════════
#  Tab5: 仕入れ検索（ステージ1＋ステージ2）
# ════════════════════════════════════════════════

with tab5:
    st.header("🛒 仕入れ候補 自動検索")
    st.caption("楽天・Yahoo!ショッピング・Yahoo!オクから候補を取得 → 利益判定を一括実行")

    sub1, sub2, sub3 = st.tabs([
        "🟥 楽天市場",
        "🟪 Yahoo!ショッピング",
        "🟧 Yahoo!オークション",
    ])

    # ─── 共通パラメータ入力欄を用意するヘルパー ───────────────
    def _search_params_form(prefix: str):
        c1, c2, c3 = st.columns(3)
        with c1:
            kw = st.text_input("検索キーワード",
                               value="九谷焼 花瓶",
                               key=f"{prefix}_kw")
            _scl = merged_category_list(True)
            cat = st.selectbox("カテゴリ",
                               _scl,
                               index=default_category_index(True),
                               key=f"{prefix}_cat")
        with c2:
            sell_usd = st.number_input("想定eBay販売価格 ($)",
                                        0.0, value=280.0, step=10.0,
                                        key=f"{prefix}_sell",
                                        help="eBayで類似品がいくらで売れそうかを入力。"
                                             "未調査ならまず250〜350で試す。")
            weight = st.number_input("推定重量 (g)",
                                      1, value=1800, step=50,
                                      key=f"{prefix}_wt")
        with c3:
            min_p = st.number_input("仕入れ価格下限 (円)",
                                     0, value=0, step=500,
                                     key=f"{prefix}_min")
            max_p = st.number_input("仕入れ価格上限 (円)",
                                     0, value=30000, step=500,
                                     key=f"{prefix}_max")

        c4, c5, c6 = st.columns(3)
        with c4:
            dest = st.selectbox("仕向地",
                                sorted(set(DESTINATION_ZONE.keys()),
                                       key=lambda x: DESTINATION_ZONE[x]),
                                index=list(DESTINATION_ZONE.keys()).index(default_dest),
                                key=f"{prefix}_dest")
        with c5:
            roi = st.number_input("目標ROI (%)",
                                   0, 200, default_target_roi, 5,
                                   key=f"{prefix}_roi")
        with c6:
            hits = st.slider("取得件数", 5, 30, 20, 5, key=f"{prefix}_hits")

        return {
            "keyword": kw,
            "category": cat if cat != "(選択)" else "",
            "sell_usd": sell_usd,
            "weight": weight,
            "min_p": min_p,
            "max_p": max_p,
            "dest": dest,
            "roi": roi,
            "hits": hits,
        }

    # ─── 検索結果表示の共通ヘルパー ───────────────
    def _render_search_results(result: dict, source_label: str):
        total = result["total_hits"]
        if total == 0:
            st.warning("該当商品が見つかりませんでした。"
                       "キーワードや価格帯を変えて再度お試しください。")
            return

        st.success(f"✅ {total} 件取得完了 "
                   f"（GO {result['go']} / HOLD {result['hold']} / STOP {result['stop']}）")

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("総件数", total)
        sm2.metric("✅ GO", result["go"],
                   delta=f"{result['go']/total*100:.0f}%" if total else "")
        sm3.metric("最高ROI", f"{result['best_roi']}%")
        sm4.metric("USD/JPY",
                   f"{result['usdjpy']:.2f}" if result["usdjpy"] else "—")

        # テーブル
        rows = []
        for r in result["results"]:
            rows.append({
                "判定": r["judge"],
                "商品名": r["product_name"][:50],
                "仕入値": f"¥{r['cost_jpy']:,}",
                "売上$": f"${r['revenue_usd']:.2f}",
                "純利益": f"¥{r['profit_jpy']:,}",
                "ROI%": r["roi_pct"],
                "店舗": r.get("shop_name", "")[:20],
                "★": f"{r.get('review_avg', 0):.1f}({r.get('review_count', 0)})",
                "URL": r.get("item_url") or r.get("auction_url") or "",
            })
        df = pd.DataFrame(rows)

        def highlight_judge(v):
            return f"background-color: {judge_color(v)}; color: white; font-weight: bold"

        styled = df.style.map(highlight_judge, subset=["判定"])
        st.dataframe(styled, use_container_width=True, height=420,
                     column_config={
                         "URL": st.column_config.LinkColumn("商品リンク",
                                                            display_text="開く"),
                     })

        # CSV ダウンロード
        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            f"⬇ {source_label} 検索結果CSV",
            data=csv_bytes,
            file_name=f"{source_label}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        # GO商品カード表示
        go_items = [r for r in result["results"] if r["judge"] == "GO"]
        if go_items:
            st.markdown(f"### 🏆 GO判定 TOP{min(5, len(go_items))}")
            for i, r in enumerate(go_items[:5], 1):
                with st.container(border=True):
                    cc = st.columns([1, 3, 1, 1, 1])
                    if r.get("image_url"):
                        try:
                            cc[0].image(r["image_url"], width=100)
                        except Exception:
                            cc[0].write("")
                    name = r["product_name"][:80]
                    url = r.get("item_url") or r.get("auction_url") or ""
                    cc[1].markdown(f"**{i}位** {name}")
                    if url:
                        cc[1].markdown(f"[商品ページ →]({url})")
                    cc[1].caption(f"店舗: {r.get('shop_name', '—')} / "
                                  f"★{r.get('review_avg', 0):.1f} "
                                  f"({r.get('review_count', 0)})")
                    cc[2].metric("ROI", f"{r['roi_pct']}%")
                    cc[3].metric("利益", f"¥{r['profit_jpy']:,}")
                    cc[4].markdown(
                        f"<div style='padding:8px;border-radius:6px;"
                        f"background:{judge_color(r['judge'])};color:white;"
                        f"text-align:center;font-weight:bold;'>{r['judge']}</div>",
                        unsafe_allow_html=True,
                    )

    # ════════ 楽天市場 ════════
    with sub1:
        st.markdown("#### 🟥 楽天市場 自動検索")
        if not os.environ.get("RAKUTEN_APP_ID"):
            st.warning(
                "サイドバーで **楽天APP_ID** を設定してください。"
                "\n\n"
                "取得先: https://webservice.rakuten.co.jp/ （無料・即時発行）"
            )

        p = _search_params_form("rak")
        if st.button("🔍 楽天で検索＆利益判定",
                     type="primary", key="rak_btn",
                     use_container_width=True):
            try:
                from rakuten_search import search_and_evaluate as rakuten_eval
                with st.spinner("楽天APIから取得中…"):
                    result = rakuten_eval(
                        keyword=p["keyword"],
                        estimated_sell_usd=p["sell_usd"],
                        estimated_weight_g=p["weight"],
                        category=p["category"],
                        destination=p["dest"],
                        target_roi=p["roi"],
                        min_price=p["min_p"],
                        max_price=p["max_p"],
                        hits=p["hits"],
                        usdjpy=usdjpy_live,
                    )
                _render_search_results(result, "rakuten")
            except Exception as e:
                st.error(f"楽天検索失敗: {e}")

    # ════════ Yahoo!ショッピング ════════
    with sub2:
        st.markdown("#### 🟪 Yahoo!ショッピング 自動検索")
        if not os.environ.get("YAHOO_APP_ID"):
            st.warning(
                "サイドバーで **Yahoo!Client ID** を設定してください。"
                "\n\n"
                "取得先: https://e.developer.yahoo.co.jp/ （無料・1日5万回まで）"
            )

        p = _search_params_form("ys")
        if st.button("🔍 Yahoo!ショッピングで検索＆利益判定",
                     type="primary", key="ys_btn",
                     use_container_width=True):
            try:
                from yahoo_shopping_search import search_and_evaluate as ys_eval
                with st.spinner("Yahoo!ショッピングAPIから取得中…"):
                    result = ys_eval(
                        keyword=p["keyword"],
                        estimated_sell_usd=p["sell_usd"],
                        estimated_weight_g=p["weight"],
                        category=p["category"],
                        destination=p["dest"],
                        target_roi=p["roi"],
                        min_price=p["min_p"],
                        max_price=p["max_p"],
                        hits=p["hits"],
                        usdjpy=usdjpy_live,
                    )
                _render_search_results(result, "yahoo_shopping")
            except Exception as e:
                st.error(f"Yahoo!ショッピング検索失敗: {e}")

    # ════════ Yahoo!オークション ════════
    with sub3:
        st.markdown("#### 🟧 Yahoo!オークション 取込＆判定")
        st.info(
            "Yahoo!オクには公式APIがないため、以下の2方式で取込みます。\n\n"
            "- **方式A（推奨）**: CSVテンプレに手動コピペ → 一括判定\n"
            "- **方式B（実験）**: URL直接入力 → HTMLから自動抽出"
        )

        ya_mode = st.radio(
            "取込方式",
            ["方式A: CSVテンプレ", "方式B: URL直接入力"],
            horizontal=True,
        )

        if ya_mode == "方式A: CSVテンプレ":
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("📥 Yahoo!オク用テンプレCSVを生成",
                             use_container_width=True):
                    from yahoo_auction_import import make_template
                    path = make_template("yahoo_auc_template.csv")
                    with open(path, "rb") as f:
                        st.download_button(
                            "⬇ yahoo_auc_template.csv をダウンロード",
                            data=f.read(),
                            file_name="yahoo_auc_template.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
            with cc2:
                st.markdown("**手順**\n\n"
                            "1. 左のボタンでテンプレDL\n"
                            "2. Yahoo!オクの商品URL・価格を手動で貼付\n"
                            "3. 「📁 CSV一括判定」タブでアップロード")

            uploaded_ya = st.file_uploader(
                "記入済みのYahoo!オクCSVをアップロード",
                type=["csv"],
                key="ya_upload",
            )
            if uploaded_ya:
                with open("_yahoo_auc_input.csv", "wb") as f:
                    f.write(uploaded_ya.read())
                from yahoo_auction_import import evaluate_csv
                with st.spinner("利益判定中…"):
                    summary = evaluate_csv(
                        input_csv="_yahoo_auc_input.csv",
                        output_csv="_yahoo_auc_result.csv",
                        go_only_csv="_yahoo_auc_go.csv",
                        usdjpy=usdjpy_live,
                    )
                st.success(f"✅ {summary['total']} 件処理完了 "
                           f"(GO {summary['go']} / HOLD {summary['hold']} / "
                           f"STOP {summary['stop']})")
                st.toast("Yahoo!オク利益判定が完了しました", icon="🛒")

                df_ya = pd.DataFrame(summary["results"])
                show_cols = ["product_name", "cost_total_jpy",
                             "revenue_usd", "profit_jpy", "roi_pct", "judge"]
                df_show = df_ya[show_cols].copy()
                df_show.columns = ["商品名", "総コスト", "売上$",
                                   "純利益", "ROI%", "判定"]

                def _hj(v):
                    return f"background-color: {judge_color(v)}; color: white; font-weight: bold"

                styled = df_show.style.map(_hj, subset=["判定"])
                st.dataframe(styled, use_container_width=True, height=400)

                with open("_yahoo_auc_go.csv", "rb") as f:
                    st.download_button(
                        "⬇ GO商品のみCSV",
                        data=f.read(),
                        file_name=f"yahoo_auc_go_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                    )

        else:  # 方式B: URL直接入力
            st.warning(
                "⚠️ Yahoo!オクのHTML解析は実験機能です。"
                "利用規約に従いリサーチ目的の少量利用に限定してください。"
                "大量連続アクセスは禁止です（1件ごとに1秒間隔）。"
            )

            p = _search_params_form("ya")

            urls_text = st.text_area(
                "Yahoo!オクURL（1行に1つ、最大10件）",
                value="https://page.auctions.yahoo.co.jp/jp/auction/xxxxxxxxx\n"
                      "https://page.auctions.yahoo.co.jp/jp/auction/yyyyyyyyy",
                height=150,
            )

            if st.button("🔍 URLから取得＆利益判定",
                         type="primary", key="ya_url_btn",
                         use_container_width=True):
                urls = [u.strip() for u in urls_text.splitlines()
                        if u.strip().startswith("http")]
                if not urls:
                    st.error("有効なURLが入力されていません")
                elif len(urls) > 10:
                    st.error("一度に処理できるのは10件までです")
                else:
                    try:
                        from yahoo_auction_import import evaluate_urls
                        with st.spinner(
                            f"{len(urls)}件を1秒間隔で取得中…"
                            f"（約{len(urls)}秒）"
                        ):
                            result = evaluate_urls(
                                urls=urls,
                                estimated_sell_usd=p["sell_usd"],
                                estimated_weight_g=p["weight"],
                                category=p["category"],
                                destination=p["dest"],
                                target_roi=p["roi"],
                                usdjpy=usdjpy_live,
                            )
                        # best_roi は未設定なので補完
                        result["best_roi"] = (result["results"][0]["roi_pct"]
                                              if result["results"] else 0)
                        _render_search_results(result, "yahoo_auction")
                    except Exception as e:
                        st.error(f"URL取込失敗: {e}")


# ════════════════════════════════════════════════
#  Tab6: 全自動リサーチ（ステージ3）
# ════════════════════════════════════════════════

with tab6:
    st.header("🎯 全自動リサーチ — キーワード1つで完結")
    st.caption(
        "eBayで相場 → 売値を自動決定 → 楽天/Yahoo!Sで仕入れ候補検索 → 利益ランキング"
    )

    # APIキー警告
    missing = []
    if not os.environ.get("EBAY_CLIENT_ID") or not os.environ.get("EBAY_CLIENT_SECRET"):
        missing.append("eBay App ID / Cert ID")
    if (not os.environ.get("RAKUTEN_APP_ID")
            and not os.environ.get("YAHOO_APP_ID")):
        missing.append("楽天APP_ID または Yahoo!Client ID（いずれか）")
    if missing:
        st.warning(
            "サイドバーで以下のAPIキーを設定してください:\n\n- "
            + "\n- ".join(missing)
        )

    # ━━━━━━━━━━━ 落札・Terapeak（手動CSV） ━━━━━━━━━━━
    with st.expander(
        "📉 落札相場（Terapeak / 手動CSV）— 実売負に近いデータ",
        expanded=False,
    ):
        st.markdown(
            "eBay **Browse API は現在出品のみ**です。**落札価格**は Terapeak や "
            "eBay の **Sold** 検索から手で転記した CSV を取り込みます。"
            "\n\n詳細はプロジェクト内 **`TERAPEAK_AND_SOLD_SPEC.md`** を参照。"
        )
        ctdl, cup = st.columns([1, 2])
        with ctdl:
            from sold_price_csv import template_csv_bytes
            st.download_button(
                "📥 落札用テンプレCSVをダウンロード",
                data=template_csv_bytes(),
                file_name="sold_prices_template.csv",
                mime="text/csv",
                key="sold_tpl_dl",
                use_container_width=True,
            )
        with cup:
            sold_up = st.file_uploader(
                "記入済みCSVをアップロード",
                type=["csv"],
                key="sold_csv_up",
                help="列: sold_price_usd, currency, shipping_usd, title, sold_date 等",
            )

        if sold_up:
            try:
                from sold_price_csv import (
                    analyze_sold_csv, format_sold_report, compare_active_vs_sold,
                )
                sold_kw = st.text_input(
                    "このCSVのキーワードメモ（任意）",
                    value=sold_up.name.replace(".csv", ""),
                    key="sold_kw_memo",
                )
                sold_a = analyze_sold_csv(sold_up, keyword=sold_kw or "")
                st.session_state["last_sold_analysis"] = sold_a

                if sold_a.get("stats"):
                    ss = sold_a["stats"]
                    st.success("落札サンプルとして取り込みました")
                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("有効件数", f"{sold_a['sampled']} 件")
                    s2.metric("中央値(落札)", f"${ss['median']}")
                    s3.metric("推奨売値", f"${sold_a['recommended_sell_usd']}")
                    s4.metric("ファイル行数", f"{sold_a['total_hits']} 行")

                    for w in sold_a.get("warnings") or []:
                        st.warning(w)

                    prev = st.session_state.get("last_active_analysis")
                    if prev and prev.get("stats") and ss:
                        cmp = compare_active_vs_sold(prev, sold_a)
                        st.info(
                            f"**Browse中央値** ${cmp['active_median']:.2f} と "
                            f"**落札中央値** ${cmp['sold_median']:.2f} の差: "
                            f"{cmp['delta_median_usd'] or 0:+.2f} USD"
                        )

                    with st.expander("テキストレポート"):
                        st.code(format_sold_report(sold_a), language="text")

                    st.session_state["sold_recommended_usd"] = sold_a[
                        "recommended_sell_usd"
                    ]
                else:
                    st.error(
                        sold_a.get("warnings", ["解析できませんでした"])[0]
                    )
            except Exception as e:
                st.error(f"CSV解析エラー: {e}")

        st.caption(
            "全自動 Step 2 では、下のチェックで「落札CSVの推奨売値」を "
            "採用できます（先にCSVをアップロードしてください）。"
        )

    # ━━━━━━━━━━━ 単発 eBay相場リサーチ ━━━━━━━━━━━
    st.subheader("📊 Step 1: eBay相場だけ調べる（売値判断用）")
    st.caption("仕入れを決める前に、eBayで今いくらで売れるかだけ確認できます")

    with st.form("ebay_only_form"):
        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            ebay_kw = st.text_input("英語キーワード",
                                     value="Kutani vase Meiji",
                                     help="eBayで検索する言葉（日本語より英語推奨）")
        with rc2:
            ebay_market = st.selectbox(
                "マーケット",
                ["アメリカ", "イギリス", "ドイツ", "フランス",
                 "オーストラリア", "カナダ"],
                index=0,
                key="ebay_mkt",
            )
        with rc3:
            ebay_cond = st.selectbox(
                "商品状態",
                list(EBAY_CONDITIONS.keys()),
                index=list(EBAY_CONDITIONS.keys()).index("未指定"),
                key="ebay_cond",
            )
        with rc4:
            ebay_limit = st.slider("分析件数", 10, 200, 50, 10)

        ebay_submit = st.form_submit_button(
            "📊 eBay相場を分析する",
            type="primary",
            use_container_width=True,
        )

    if ebay_submit:
        try:
            from ebay_research import analyze_prices, MARKETPLACES
            with st.spinner("eBay Browse APIで価格データを取得中…"):
                analysis = analyze_prices(
                    keyword=ebay_kw,
                    limit=ebay_limit,
                    marketplace=MARKETPLACES.get(ebay_market, "EBAY_US"),
                    condition=EBAY_CONDITIONS.get(ebay_cond, ""),
                )

            if analysis["total_hits"] == 0:
                st.error("該当商品が見つかりませんでした。英語キーワードを変更してお試しください。")
            else:
                st.session_state["last_active_analysis"] = analysis
                s = analysis["stats"]

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("eBay出品総数", f"{analysis['total_hits']:,} 件")
                m2.metric("分析対象", f"{analysis['sampled']} 件",
                          help="外れ値除去後のサンプル数")
                m3.metric("中央値", f"${s['median']}")
                m4.metric("価格幅", f"${s['min']}〜${s['max']}")

                # 推奨売値4案
                st.markdown("### 💡 推奨販売価格（4戦略）")
                p1, p2, p3, p4 = st.columns(4)
                with p1:
                    st.metric("⚡ 速売 (P25)",
                              f"${analysis['safe_sell_usd']}",
                              help="早く売り切りたい")
                with p2:
                    st.metric("🎯 バランス",
                              f"${analysis['recommended_sell_usd']}",
                              delta="採用推奨",
                              delta_color="normal",
                              help="中央値×92%")
                with p3:
                    st.metric("💰 標準 (中央値)",
                              f"${analysis['aggressive_sell_usd']}")
                with p4:
                    st.metric("👑 強気 (P75)",
                              f"${analysis['premium_sell_usd']}",
                              help="時間かけて高く売る")

                # 価格ヒストグラム
                st.markdown("### 📊 価格分布")
                prices = [it["price_usd"] for it in analysis["items"]
                          if it["price_usd"] > 0]
                fig = go.Figure()
                fig.add_trace(go.Histogram(
                    x=prices,
                    nbinsx=20,
                    marker_color="#6366f1",
                    opacity=0.8,
                ))
                fig.add_vline(x=s["median"], line_dash="solid",
                              line_color="#22c55e",
                              annotation_text=f"中央値 ${s['median']}")
                fig.add_vline(x=s["p25"], line_dash="dash",
                              line_color="#f59e0b",
                              annotation_text=f"P25 ${s['p25']}")
                fig.add_vline(x=s["p75"], line_dash="dash",
                              line_color="#ef4444",
                              annotation_text=f"P75 ${s['p75']}")
                fig.update_layout(
                    xaxis_title="価格 (USD)",
                    yaxis_title="出品数",
                    height=350,
                    margin=dict(t=30, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

                # サンプル出品
                with st.expander("📋 eBay実際の出品例（上位20件）"):
                    rows = []
                    for it in analysis["items"]:
                        rows.append({
                            "価格$": it["price_usd"],
                            "送料$": it["shipping_usd"],
                            "合計$": it["total_usd"],
                            "状態": it["condition"],
                            "出品者": it["seller"],
                            "評価%": it["seller_feedback_pct"],
                            "所在": it["location"],
                            "タイトル": it["title"][:70],
                            "URL": it["item_url"],
                        })
                    df_ebay = pd.DataFrame(rows)
                    st.dataframe(
                        df_ebay, use_container_width=True, height=400,
                        column_config={
                            "URL": st.column_config.LinkColumn(
                                "リンク", display_text="開く",
                            ),
                        },
                    )
        except Exception as e:
            st.error(f"eBay相場分析に失敗: {e}")

    st.divider()

    # ━━━━━━━━━━━ 全自動パイプライン ━━━━━━━━━━━
    st.subheader("🚀 Step 2: 全自動パイプライン（eBay × 仕入れ元 × 利益判定）")

    with st.form("full_auto_form"):
        fa1, fa2 = st.columns(2)
        with fa1:
            fa_kw_ebay = st.text_input(
                "eBay検索キーワード（英語推奨）",
                value="Kutani vase Meiji",
            )
            fa_kw_src = st.text_input(
                "仕入れ元検索キーワード（日本語）",
                value="九谷焼 花瓶",
                help="楽天/Yahoo!Sで検索する言葉",
            )
            _fcl = merged_category_list(True)
            fa_cat = st.selectbox(
                "カテゴリ",
                _fcl,
                index=default_category_index(True),
                key="fa_cat",
            )
        with fa2:
            fa_source = st.radio(
                "仕入れ元",
                ["楽天市場", "Yahoo!ショッピング"],
                horizontal=True,
            )
            fa_weight = st.number_input("推定重量 (g)",
                                         1, value=1800, step=50, key="fa_wt")
            fa_dest = st.selectbox(
                "仕向地",
                sorted(set(DESTINATION_ZONE.keys()),
                       key=lambda x: DESTINATION_ZONE[x]),
                index=list(DESTINATION_ZONE.keys()).index(default_dest),
                key="fa_dest",
            )

        fa3, fa4, fa5 = st.columns(3)
        with fa3:
            fa_strategy = st.selectbox(
                "売値戦略",
                [("recommended", "🎯 バランス（中央値×92%）"),
                 ("safe", "⚡ 速売（P25）"),
                 ("aggressive", "💰 標準（中央値）"),
                 ("premium", "👑 強気（P75）")],
                format_func=lambda x: x[1],
                index=0,
            )[0]
        with fa4:
            fa_roi = st.number_input("目標ROI (%)",
                                      0, 200, default_target_roi, 5, key="fa_roi")
        with fa5:
            fa_max_cost = st.number_input(
                "仕入れ値上限 (円)",
                0, value=30000, step=1000, key="fa_max",
            )

        fa_cond = st.selectbox(
            "eBay相場で使う商品状態",
            list(EBAY_CONDITIONS.keys()),
            index=list(EBAY_CONDITIONS.keys()).index("未指定"),
            key="fa_cond",
        )

        fa_prefer_sold = st.checkbox(
            "落札CSVの推奨売値を売値に使う（上の「落札相場」でCSVをアップロード済み）",
            value=False,
            key="fa_prefer_sold",
            help="チェック時は Browse API の戦略より、手動CSVの recommended を優先します。",
        )

        fa_submit = st.form_submit_button(
            "🚀 全自動リサーチを実行",
            type="primary",
            use_container_width=True,
        )

    if fa_submit:
        try:
            with st.spinner(
                "① eBayで相場分析 → ② 売値決定 → "
                "③ 仕入れ元検索 → ④ 利益判定…（30〜60秒）"
            ):
                # eBay検索と仕入れ元検索でキーワードを分けるため、
                # full_auto_researchを拡張する代わりに手動で2段階実行
                from ebay_research import analyze_prices

                # Step 1: eBay相場（仕向地に応じたマーケット）
                ebay_a = analyze_prices(
                    keyword=fa_kw_ebay,
                    limit=50,
                    marketplace=marketplace_for_destination(fa_dest),
                    condition=EBAY_CONDITIONS.get(fa_cond, ""),
                )
                if ebay_a["total_hits"] == 0:
                    st.error(
                        f"eBay '{fa_kw_ebay}' で商品が見つかりませんでした。"
                        f"英語キーワードを見直してください。"
                    )
                    st.stop()

                # Step 2: 売値決定（落札CSV優先オプション）
                strategy_map = {
                    "recommended": "recommended_sell_usd",
                    "safe": "safe_sell_usd",
                    "aggressive": "aggressive_sell_usd",
                    "premium": "premium_sell_usd",
                }
                sell_usd = ebay_a[strategy_map[fa_strategy]]
                price_source = "browse_api"
                if fa_prefer_sold and st.session_state.get("sold_recommended_usd"):
                    sell_usd = float(st.session_state["sold_recommended_usd"])
                    price_source = "sold_csv"
                elif fa_prefer_sold:
                    st.warning(
                        "「落札CSVを優先」がオンですが、先に Expander で "
                        "CSV をアップロードしてください。Browse API の売値で続行します。"
                    )

                # Step 3+4: 仕入れ元検索 + 利益判定
                cat = fa_cat if fa_cat != "(選択)" else ""
                if fa_source == "楽天市場":
                    from rakuten_search import search_and_evaluate as rak_eval
                    src_result = rak_eval(
                        keyword=fa_kw_src,
                        estimated_sell_usd=sell_usd,
                        estimated_weight_g=fa_weight,
                        category=cat,
                        destination=fa_dest,
                        target_roi=fa_roi,
                        max_price=fa_max_cost,
                        hits=30,
                        usdjpy=usdjpy_live,
                    )
                else:
                    from yahoo_shopping_search import search_and_evaluate as ys_eval
                    src_result = ys_eval(
                        keyword=fa_kw_src,
                        estimated_sell_usd=sell_usd,
                        estimated_weight_g=fa_weight,
                        category=cat,
                        destination=fa_dest,
                        target_roi=fa_roi,
                        max_price=fa_max_cost,
                        hits=30,
                        usdjpy=usdjpy_live,
                    )

            # ─── 結果表示 ───
            st.success("✅ 全自動リサーチ完了")
            st.toast("全自動リサーチの結果を表示しています", icon="🎯")
            if price_source == "sold_csv":
                st.info(
                    "採用した売値は **落札・手動CSV** の推奨値です（"
                    "`TERAPEAK_AND_SOLD_SPEC.md` 参照）。"
                )

            # サマリーカード
            st.markdown("### 📋 リサーチサマリー")
            sum1, sum2, sum3, sum4 = st.columns(4)
            sum1.metric("eBay出品数", f"{ebay_a['total_hits']:,}")
            sum2.metric(
                "採用売値",
                f"${sell_usd}",
                delta=f"中央値${ebay_a['stats']['median']}比 "
                      f"{sell_usd - ebay_a['stats']['median']:+.2f}",
            )
            sum3.metric("仕入れ候補", f"{src_result['total_hits']} 件")
            sum4.metric(
                "✅ 利益GO",
                f"{src_result['go']} 件",
                delta=f"{src_result['go']/src_result['total_hits']*100:.0f}%"
                      if src_result["total_hits"] else "",
            )

            # eBay統計を折りたたみで
            with st.expander("📊 eBay相場データ", expanded=False):
                s = ebay_a["stats"]
                pp1, pp2, pp3, pp4 = st.columns(4)
                pp1.metric("最安", f"${s['min']}")
                pp2.metric("P25", f"${s['p25']}")
                pp3.metric("中央値", f"${s['median']}")
                pp4.metric("P75", f"${s['p75']}")

            # 仕入れ候補ランキング
            st.markdown("### 🏆 利益ランキング")
            if src_result["total_hits"] == 0:
                st.warning(
                    f"仕入れ元で '{fa_kw_src}' にヒットしませんでした。"
                    f"キーワードを変えてお試しください。"
                )
            else:
                # テーブル
                rows = []
                for r in src_result["results"]:
                    rows.append({
                        "判定": r["judge"],
                        "商品名": r["product_name"][:50],
                        "仕入値": f"¥{r['cost_jpy']:,}",
                        "売値$": f"${sell_usd}",
                        "純利益": f"¥{r['profit_jpy']:,}",
                        "ROI%": r["roi_pct"],
                        "店舗": r.get("shop_name", "")[:20],
                        "URL": r.get("item_url", ""),
                    })
                df_final = pd.DataFrame(rows)

                def _hj(v):
                    return (f"background-color: {judge_color(v)}; "
                            f"color: white; font-weight: bold")

                styled = df_final.style.map(_hj, subset=["判定"])
                st.dataframe(
                    styled, use_container_width=True, height=450,
                    column_config={
                        "URL": st.column_config.LinkColumn(
                            "リンク", display_text="開く",
                        ),
                    },
                )

                # GO TOP3カード
                go_items = [r for r in src_result["results"]
                            if r["judge"] == "GO"][:3]
                if go_items:
                    st.markdown("### 🥇 GO判定 TOP3（すぐ仕入れ推奨）")
                    for i, r in enumerate(go_items, 1):
                        with st.container(border=True):
                            cc = st.columns([1, 3, 1, 1, 1])
                            if r.get("image_url"):
                                try:
                                    cc[0].image(r["image_url"], width=120)
                                except Exception:
                                    pass
                            cc[1].markdown(
                                f"**{i}位** {r['product_name'][:60]}"
                            )
                            if r.get("item_url"):
                                cc[1].markdown(
                                    f"[仕入ページ →]({r['item_url']})"
                                )
                            cc[1].caption(
                                f"店舗: {r.get('shop_name', '')} / "
                                f"★{r.get('review_avg', 0):.1f}"
                            )
                            cc[2].metric("ROI", f"{r['roi_pct']}%")
                            cc[3].metric("純利益", f"¥{r['profit_jpy']:,}")
                            cc[4].metric("売値", f"${sell_usd}")

                # CSV DL
                csv_bytes = df_final.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇ 全結果CSVダウンロード",
                    data=csv_bytes,
                    file_name=f"fullauto_{fa_kw_src}_"
                              f"{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                )
        except Exception as e:
            st.error(f"全自動リサーチに失敗: {e}")
            import traceback
            with st.expander("詳細ログ"):
                st.code(traceback.format_exc())


# ════════════════════════════════════════════════
#  Tab7: 購買心理・先読み
# ════════════════════════════════════════════════

with tab7:
    st.header("🧠 購買心理・先読み")
    st.caption(
        "行事・季節・曜日・仕向け・カテゴリの心理タグに加え、"
        "**南半球／寒帯・暑帯／雨季乾季**に応じて「今そこで増えやすいニーズ」を推定します。"
        " 個人の心情を断定するものではありません。"
    )

    st.subheader("📅 イベント別・出品前倒しカレンダー")
    st.caption(
        "年度末・年末年始・クリスマス・誕生日・結婚記念日・出産祝い・入学・卒業・就職など、"
        "**需要ピークの何週間前から**出品・在庫を並べるとよいかの目安です。"
    )
    ev_dest = st.selectbox(
        "イベントの習慣（仕向け国）",
        sorted(set(DESTINATION_ZONE.keys()),
               key=lambda x: DESTINATION_ZONE[x]),
        index=list(DESTINATION_ZONE.keys()).index(default_dest),
        key="ev_cal_dest",
    )
    ev_horizon = st.slider("表示する先の月数", 3, 14, 8, key="ev_horizon")
    ev_rows = build_listing_calendar(ev_dest, date.today(), ev_horizon)
    for line in upcoming_actions(ev_dest, date.today())[:5]:
        st.info(line)

    if ev_rows:
        df_ev = pd.DataFrame(ev_rows)
        drop_vis = {"product_hints_ja", "notes_ja", "event_name_en", "event_id",
                    "timing_type", "demand_peak_weeks_before"}
        vis_cols = [c for c in df_ev.columns if c not in drop_vis]
        st.dataframe(
            df_ev[vis_cols],
            use_container_width=True,
            height=340,
        )
        with st.expander("品目ヒント・注意（イベント別）"):
            for r in ev_rows[:30]:
                peak = r.get("approx_peak_month") or r.get("approx_peak", "")
                st.markdown(f"**{r['event_name_ja']}** — {peak}")
                st.caption(" · ".join(r.get("product_hints_ja", [])[:8]))
                if r.get("notes_ja"):
                    st.caption(r["notes_ja"])
        st.download_button(
            "⬇ イベントカレンダーCSV",
            data=df_ev.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"event_calendar_{ev_dest}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="ev_csv_dl",
        )
        with st.expander("テキストレポート全文"):
            st.code(
                format_listing_calendar_report(ev_dest, date.today(), ev_horizon),
                language="text",
            )
    st.divider()

    mcat = merge_categories_for_ui(CATEGORIES)
    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config",
        "product_catalog.json",
    )
    st.info(
        f"品目ジャンルの追加・変更は **`config/product_catalog.json`** を編集してください。"
        f"（このファイル: `{cfg_path}`）"
    )

    with st.form("psych_form"):
        p_cat = st.selectbox(
            "カテゴリ",
            sorted(mcat.categories_display.keys()),
            index=sorted(mcat.categories_display.keys()).index("骨董品・陶磁器")
            if "骨董品・陶磁器" in mcat.categories_display else 0,
        )
        st.caption(f"想定利益率目安: **{mcat.categories_display.get(p_cat, '—')}**")
        if p_cat in mcat.extension_keys:
            st.success("拡張カタログで定義されたカテゴリです")

        p_dest = st.selectbox(
            "仕向け（文化・行事の補正）",
            sorted(set(DESTINATION_ZONE.keys()),
                   key=lambda x: DESTINATION_ZONE[x]),
            index=list(DESTINATION_ZONE.keys()).index(default_dest),
        )
        p_day = st.date_input("基準日", value=date.today())
        p_mood = st.slider(
            "社会ムード（体感）",
            -1.0,
            1.0,
            0.0,
            0.1,
            help="ニュースや景気の空気をざっくり。不安(-)／楽観(+)",
        )
        p_run = st.form_submit_button("先読みを計算", type="primary", use_container_width=True)

    if p_run:
        pi = compute_purchase_intent(
            p_cat,
            p_dest,
            p_day,
            social_mood=p_mood,
        )
        g1, g2, g3, g4, g5 = st.columns(5)
        g1.metric("意欲スコア", f"{pi['intent_score']}/100")
        g2.metric("需要補正（参考）", f"×{pi['intent_multiplier']}")
        g3.metric("気候ブレンド後", f"×{pi['intent_multiplier_climate_blended']}")
        g4.metric("仕向け補正", f"×{pi['destination_multiplier']}")
        g5.metric("ムード調整", f"{pi['mood_adjustment']:+.4f}")

        cc = pi.get("climate_context") or {}
        if cc:
            st.markdown("#### 🌍 現地の季節・気候（半球・寒暖）")
            st.write(
                f"**{cc.get('climate_label_ja', '—')}** ・ "
                f"**{cc.get('local_season_ja', '—')}** "
                f"（半球: {cc.get('hemisphere', '—')}）"
            )
            st.info(cc.get("hemisphere_note", ""))
            st.markdown("**その時期に増えやすいニーズ（目安）**")
            for n in cc.get("need_insights_ja") or []:
                st.markdown(f"- {n}")
            st.success(
                f"選択カテゴリの季節相性: ×{cc.get('category_fit_multiplier', 1)} "
                f"— {cc.get('category_fit_note', '')}"
            )

        st.markdown("#### 先読みメモ（3ヶ月）")
        st.write(pi["forward_horizon_note"])

        st.markdown("#### 心理タグ")
        st.write(", ".join(f"`{t}`" for t in pi["psych_tags"]))

        fig_p = go.Figure(go.Bar(
            x=[r["contribution"] for r in pi["factors"]],
            y=[r["label"] for r in pi["factors"]],
            orientation="h",
        ))
        fig_p.update_layout(
            height=max(280, len(pi["factors"]) * 36),
            margin=dict(l=160, t=20, b=20),
            xaxis_title="寄与（モデル内スケール）",
        )
        st.plotly_chart(fig_p, use_container_width=True)

        st.code(format_intent_report(pi), language="text")
        st.caption(pi["disclaimer"])

    with st.expander("心理ドライバー一覧（開発者向け）"):
        st.json({k: v["label"] for k, v in PSYCH_DRIVERS.items()})
