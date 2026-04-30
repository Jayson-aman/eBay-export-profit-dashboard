"""
amazon_fba_research_app.py — 楽天/Yahoo!ショッピングからAmazon FBA向け仕入れ候補を探すアプリ。

使い方:
    streamlit run amazon_fba_research_app.py

携帯のキャリア回線からPC上の本アプリへHTTPSでアクセスする例:
    STREAMLIT_APP=amazon_fba_research_app.py ./start_external_access.sh
    （cloudflared 要・画面の説明に同一手順あり）

GitHub に push し Streamlit Community Cloud と連携すると、スマホから https://....streamlit.app で常時利用できます（手順は DEPLOY.md）。

必要に応じて以下を設定:
    export RAKUTEN_APP_ID="..."
    export YAHOO_APP_ID="..."
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from amazon_fba_tools import (
    AmazonFbaConfig,
    rank_amazon_fba_candidates,
    summarize_ranked_candidates,
)
from ui_modern import apply_modern_ui
from amasearch import (
    AMASEARCH_APP_STORE_SEARCH,
    AMASEARCH_GOOGLE_PLAY,
    AMASEARCH_OFFICIAL,
    amazon_co_jp_search_url,
)
from barcode_jan import normalize_product_barcode, search_rakuten_yahoo_shopping

# 携帯ブラウザから開く用途（Keepa はブラウザ版。アプリは各ストアで検索）
KEEPA_WEB = "https://keepa.com/"
AMAZON_CO_JP_HOME = "https://www.amazon.co.jp/"
STREAMLIT_DEPLOY_DOC = "https://docs.streamlit.io/streamlit-community-cloud/get-started"


def _api_key_default(name: str) -> str:
    """環境変数、なければ Streamlit Secrets（Community Cloud 想定）。"""
    env = (os.environ.get(name) or "").strip()
    if env:
        return env
    try:
        if not hasattr(st, "secrets"):
            return ""
        return str(st.secrets[name]).strip()
    except Exception:
        return ""


st.set_page_config(
    page_title="Amazon FBA 利益20%リサーチ",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_modern_ui()


SOURCE_LABELS = {
    "rakuten": "楽天市場",
    "yahoo_shopping": "Yahoo!ショッピング",
}

PREMIUM_SEARCH_PRESETS = {
    "手入力": "",
    "限定・廃盤": "限定 廃盤 希少",
    "日本製・職人": "日本製 職人 高級",
    "伝統工芸": "九谷焼 有田焼 南部鉄器 燕三条",
    "ホビー限定品": "初回限定 特装版 復刻 コラボ",
    "完売・終売品": "完売 生産終了 終売 レア",
    "購入制限・抽選": "お一人様 1名様 抽選 数量限定 限定",
}

DISPLAY_COLUMNS = [
    "buy_timing",
    "judge",
    "product_name",
    "source",
    "shop_name",
    "source_cost_jpy",
    "effective_cost_jpy",
    "amazon_price_jpy",
    "profit_jpy",
    "margin_pct",
    "roi_pct",
    "premium_score",
    "sell_through_score",
    "inventory_risk",
    "popularity_score",
    "review_avg",
    "review_count",
    "premium_flags",
    "commodity_flags",
    "restriction_flags",
    "buy_timing_note",
    "jan_code",
    "item_url",
    "amazon_search_url",
]

PURCHASE_COLUMNS = [
    "recommended_action",
    "product_name",
    "source",
    "shop_name",
    "buy_quantity",
    "source_cost_jpy",
    "effective_cost_jpy",
    "amazon_price_jpy",
    "profit_jpy",
    "margin_pct",
    "premium_score",
    "sell_through_score",
    "inventory_risk",
    "item_url",
    "amazon_search_url",
    "manual_checks",
]


def _source_display(value: str) -> str:
    return SOURCE_LABELS.get(value, value)


@st.cache_data(ttl=600)
def search_sources(
    keyword: str,
    min_price: int,
    max_price: int,
    hits: int,
    use_rakuten: bool,
    use_yahoo: bool,
    rakuten_app_id: str,
    yahoo_app_id: str,
) -> tuple[list[dict], list[str]]:
    """楽天/Yahoo!ショッピングを検索して候補をまとめる。"""

    rows: list[dict] = []
    errors: list[str] = []

    if use_rakuten:
        try:
            from rakuten_search import search as rakuten_search

            rows.extend(
                rakuten_search(
                    keyword=keyword,
                    min_price=min_price,
                    max_price=max_price,
                    hits=hits,
                    sort="-reviewCount",
                    app_id=rakuten_app_id or None,
                )
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"楽天市場: {e}")

    if use_yahoo:
        try:
            from yahoo_shopping_search import search as yahoo_search

            rows.extend(
                yahoo_search(
                    keyword=keyword,
                    min_price=min_price,
                    max_price=max_price,
                    hits=hits,
                    sort="-review_count",
                    app_id=yahoo_app_id or None,
                )
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"Yahoo!ショッピング: {e}")

    return rows, errors


def _render_metric_row(summary: dict[str, int]) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("候補数", summary["total"])
    c2.metric("GO", summary["go"])
    c3.metric("要確認", summary["check"])
    c4.metric("利益あり", summary["hold"])
    c5.metric("見送り", summary["stop"])


def _prepare_download_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    cols = [c for c in DISPLAY_COLUMNS if c in df.columns]
    df = df[cols].copy()
    df["source"] = df["source"].map(_source_display)
    return df


def _prepare_purchase_df(rows: list[dict]) -> pd.DataFrame:
    """手動承認して仕入れるための実行リストを作る。"""

    approved = [
        dict(r)
        for r in rows
        if r.get("judge") == "GO"
        and r.get("inventory_risk") == "低"
        and not r.get("restriction_flags")
    ]
    for row in approved:
        row["buy_quantity"] = 1
        row["recommended_action"] = "手動確認後に仕入れ"
        row["manual_checks"] = (
            "Amazon同一JAN/型番, 出品制限, FBA手数料, Keepa月間販売数, "
            "出品者数, カート価格, 返品リスク"
        )

    df = pd.DataFrame(approved)
    if df.empty:
        return df
    cols = [c for c in PURCHASE_COLUMNS if c in df.columns]
    df = df[cols].copy()
    df["source"] = df["source"].map(_source_display)
    return df


def _prepare_amazon_listing_df(rows: list[dict]) -> pd.DataFrame:
    """Amazon出品登録の下書きCSV。SKU等はセラー側で最終調整する。"""

    approved = [
        r for r in rows
        if r.get("judge") == "GO"
        and r.get("inventory_risk") == "低"
        and not r.get("restriction_flags")
    ]
    listing_rows = []
    for idx, row in enumerate(approved, start=1):
        listing_rows.append({
            "sku": f"FBA-AUTO-{idx:04d}",
            "product_name_reference": row.get("product_name", ""),
            "external_product_id": "",
            "external_product_id_type": "",
            "price": row.get("amazon_price_jpy", ""),
            "quantity": 1,
            "fulfillment_channel": "AMAZON_NA",
            "condition_type": "New",
            "source_url": row.get("item_url", ""),
            "amazon_check_url": row.get("amazon_search_url", ""),
            "note": "同一JAN/型番と出品制限を確認してから登録",
        })
    return pd.DataFrame(listing_rows)


st.title("📦 Amazon FBA 利益20%リサーチ")
st.caption(
    "楽天市場・Yahoo!ショッピングの商品を自動取得し、Amazon FBAで販売した場合の"
    "利益率20%以上候補をスクリーニングします。プレミアム性と売れ残りリスクも同時に見ます。"
)

with st.sidebar:
    st.header("検索API")
    _rak_def = _api_key_default("RAKUTEN_APP_ID")
    _yah_def = _api_key_default("YAHOO_APP_ID")
    rakuten_app_id = st.text_input(
        "楽天APP_ID",
        value=_rak_def,
        type="password",
        help="https://webservice.rakuten.co.jp/ で無料取得。Streamlit Cloud では Secrets の RAKUTEN_APP_ID が初期値になります。",
    )
    yahoo_app_id = st.text_input(
        "Yahoo! Client ID",
        value=_yah_def,
        type="password",
        help="https://e.developer.yahoo.co.jp/ で無料取得。Streamlit Cloud では Secrets の YAHOO_APP_ID が初期値になります。",
    )
    if rakuten_app_id:
        os.environ["RAKUTEN_APP_ID"] = rakuten_app_id
    if yahoo_app_id:
        os.environ["YAHOO_APP_ID"] = yahoo_app_id

    with st.expander("携帯でアマサーチ・Keepaと一緒に見る", expanded=False):
        st.markdown(
            "**おすすめ（常時・スマホ）:** リポジトリを **GitHub に push** し、"
            "[Streamlit Community Cloud](https://streamlit.io/cloud) でこのアプリをデプロイすると、"
            "`https://….streamlit.app` をスマホブラウザで開けます。手順はリポジトリ直下の **`DEPLOY.md`**。"
        )
        st.link_button("Streamlit Cloud 公式ドキュメント", STREAMLIT_DEPLOY_DOC, use_container_width=True)
        st.markdown(
            "**一時的（自宅PC）:** **`start_external_access.sh`** で cloudflared トンネル "
            "（終わったら **Ctrl+C**）。URL を知る人は誰でも開けます。"
        )
        st.code(
            "STREAMLIT_APP=amazon_fba_research_app.py ./start_external_access.sh",
            language="bash",
        )
        st.caption(
            "スマホでは **Safari または Chrome** を推奨。アプリを1タブ、アマサーチ・Keepaを **別タブ** にすると比較しやすいです。"
        )
        r1, r2, r3 = st.columns(3)
        with r1:
            st.link_button("アマサーチ 公式", AMASEARCH_OFFICIAL, use_container_width=True)
        with r2:
            st.link_button("Keepa（価格推移）", KEEPA_WEB, use_container_width=True)
        with r3:
            st.link_button("Amazon.co.jp", AMAZON_CO_JP_HOME, use_container_width=True)
        r4, r5 = st.columns(2)
        with r4:
            st.link_button("アマサーチ（Google Play）", AMASEARCH_GOOGLE_PLAY, use_container_width=True)
        with r5:
            st.link_button("アマサーチ（App Store 検索）", AMASEARCH_APP_STORE_SEARCH, use_container_width=True)

    st.divider()
    st.header("Amazon FBA条件")
    amazon_price_jpy = st.number_input(
        "Amazon想定販売価格（円）",
        min_value=1,
        value=3000,
        step=100,
        help="Amazon商品ページやセラーセントラルで確認した販売価格を入れてください。",
    )
    referral_fee_rate = st.slider("Amazon販売手数料率 (%)", 5, 30, 10, 1) / 100
    fba_fee_jpy = st.number_input("FBA配送代行手数料（円/個）", 0, 10000, 600, 10)
    inbound_shipping_jpy = st.number_input("FBA納品送料（円/個）", 0, 5000, 120, 10)
    prep_cost_jpy = st.number_input("梱包・ラベル等（円/個）", 0, 5000, 80, 10)
    other_cost_jpy = st.number_input("その他コスト（円/個）", 0, 10000, 0, 10)
    return_allowance_rate = st.slider("返品・値下げバッファ (%)", 0, 20, 2, 1) / 100
    target_margin_pct = st.slider("目標利益率（売上比 %）", 5, 60, 20, 1)
    use_points_as_discount = st.checkbox("ポイント還元を実質値引きに含める", value=True)

    st.divider()
    st.header("人気判定")
    min_review_count = st.number_input("最低レビュー数", 0, 10000, 5, 1)
    min_review_avg = st.slider("最低レビュー評価", 0.0, 5.0, 3.5, 0.1)

    st.divider()
    st.header("売れ残り回避")
    premium_only = st.checkbox("プレミアム候補を優先判定する", value=True)
    show_premium_only = st.checkbox("プレミアム候補だけ表示", value=False)
    min_premium_score = st.slider("最低プレミアムスコア", 0, 100, 45, 5)
    min_sell_through_score = st.slider("最低売れやすさスコア", 0, 100, 55, 5)

config = AmazonFbaConfig(
    amazon_price_jpy=int(amazon_price_jpy),
    referral_fee_rate=referral_fee_rate,
    fba_fee_jpy=int(fba_fee_jpy),
    inbound_shipping_jpy=int(inbound_shipping_jpy),
    prep_cost_jpy=int(prep_cost_jpy),
    other_cost_jpy=int(other_cost_jpy),
    return_allowance_rate=return_allowance_rate,
    target_margin_pct=float(target_margin_pct),
    min_review_count=int(min_review_count),
    min_review_avg=float(min_review_avg),
    use_points_as_discount=use_points_as_discount,
    premium_only=premium_only,
    min_premium_score=float(min_premium_score),
    min_sell_through_score=float(min_sell_through_score),
)

with st.expander("📷 JAN / バーコードで買い時判定", expanded=False):
    st.caption(
        "楽天・Yahoo!ショッピングは **タイトル等に載っているJAN** をキーワード検索で拾います。"
        "ヒットしない商品もあります。サイドバーの「Amazon想定販売価格」は、カート想定と揃えてください。"
        " Amazonの実勢・Keepaの販売数は別途確認が必要です。"
    )
    with st.form("jan_buy_form"):
        jan_input = st.text_input(
            "JAN / EAN / UPC（8〜13桁の数字）",
            placeholder="4901234567890",
            help="カメラアプリやサンワのスキャナで読んだ列をそのまま貼り付け可（ハイフンは無視されます）。",
        )
        jan_hits_each = st.slider("JAN検索・各モール最大件数", 5, 30, 20)
        jan_submitted = st.form_submit_button("JANで検索して買い時判定", type="secondary")

if jan_submitted:
    code, bc_err = normalize_product_barcode(jan_input)
    if bc_err:
        st.error(bc_err)
    else:
        with st.spinner(f"JAN {code} で楽天・Yahoo!を検索しています…"):
            jan_items, jan_errs = search_rakuten_yahoo_shopping(code, hits=jan_hits_each)
        for _e in jan_errs:
            st.warning(_e)
        if not jan_items:
            st.error(
                "0件でした。JANが商品名に載っていないか、APIキー未設定の可能性があります。"
                " キーワード検索に切り替えるか、アマサーチで同一品を確認してください。"
            )
        else:
            jan_url = amazon_co_jp_search_url(code)
            rows_j = rank_amazon_fba_candidates(jan_items, config)
            for _r in rows_j:
                _r["amazon_search_url"] = jan_url
                _r["jan_code"] = code
            best = rows_j[0]
            st.subheader(f"JAN `{code}` の買い時目安")
            cj1, cj2, cj3 = st.columns(3)
            cj1.metric("買い時", best.get("buy_timing", "—"))
            cj2.metric("最優先の判定", best.get("judge", "—"))
            cj3.metric("実質最安仕入れ（候補内）", f"¥{min(r['effective_cost_jpy'] for r in rows_j):,}")
            st.info(best.get("buy_timing_note", ""))
            st.link_button("Amazon.co.jp でこのJANを検索", jan_url, use_container_width=True)
            _costs = sorted({r["effective_cost_jpy"] for r in rows_j})
            if len(_costs) >= 2 and _costs[0] > 0:
                _spread = (_costs[-1] - _costs[0]) / _costs[-1]
                if _spread >= 0.15:
                    st.warning(
                        f"同一JAN候補の実質仕入れに幅があります（¥{_costs[0]:,} 〜 ¥{_costs[-1]:,}）。"
                        "別SKUやセット品でないか商品ページを開いて確認してください。"
                    )
            df_j = _prepare_download_df(rows_j)
            st.dataframe(
                df_j,
                use_container_width=True,
                column_config={
                    "item_url": st.column_config.LinkColumn("仕入れURL"),
                    "amazon_search_url": st.column_config.LinkColumn("Amazon(JAN検索)"),
                    "margin_pct": st.column_config.NumberColumn("利益率%", format="%.1f"),
                    "roi_pct": st.column_config.NumberColumn("ROI%", format="%.1f"),
                    "premium_score": st.column_config.NumberColumn("プレミアム", format="%.1f"),
                    "sell_through_score": st.column_config.NumberColumn("売れやすさ", format="%.1f"),
                    "profit_jpy": st.column_config.NumberColumn("利益", format="¥%d"),
                },
            )
            st.download_button(
                "JAN判定結果をCSV",
                data=df_j.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"jan_{code}_buy_timing.csv",
                mime="text/csv",
                use_container_width=True,
                key="dl_jan_csv",
            )
    st.divider()

with st.form("search_form"):
    c0, c1 = st.columns([1, 2])
    with c0:
        preset_name = st.selectbox(
            "プレミアム探索テンプレ",
            list(PREMIUM_SEARCH_PRESETS.keys()),
            index=1,
        )
    with c1:
        default_keyword = PREMIUM_SEARCH_PRESETS[preset_name] or "限定 廃盤 希少"
        keyword = st.text_input("検索キーワード", value=default_keyword)

    c2, c3 = st.columns(2)
    with c2:
        min_price = st.number_input("最低仕入価格", 0, 1_000_000, 0, 100)
    with c3:
        max_price = st.number_input("最高仕入価格", 1, 1_000_000, 15000, 100)

    c4, c5, c6 = st.columns(3)
    with c4:
        hits = st.slider("各モール取得件数", 5, 50, 30, 5)
    with c5:
        use_rakuten = st.checkbox("楽天市場", value=True)
    with c6:
        use_yahoo = st.checkbox("Yahoo!ショッピング", value=True)

    submitted = st.form_submit_button("候補を検索して利益判定", type="primary")

st.info(
    "Amazon価格の自動取得は入れていません。PA-API/SP-APIの認証なしスクレイピングは規約リスクがあるため、"
    "このアプリではAmazon検索リンクで価格・出品制限・FBA手数料・Keepaの売れ行きを確認する設計です。"
)
st.warning(
    "売れ残り回避のスコアはレビュー・評価・商品名の希少性キーワードによる推定です。"
    "仕入れ前にAmazonランキング、Keepaの月間販売数、出品者数、カート価格の推移を必ず確認してください。"
)
st.warning(
    "このアプリは自動決済・自動購入は行いません。楽天/Yahoo!には一般向け購入APIがなく、"
    "購入ボットや決済情報の自動入力は規約・セキュリティ上のリスクが高いため、仕入れは承認リストから手動確認してください。"
)

if submitted:
    if not keyword.strip():
        st.error("検索キーワードを入力してください。")
        st.stop()
    if not use_rakuten and not use_yahoo:
        st.error("少なくとも1つの仕入れ元を選んでください。")
        st.stop()

    with st.spinner("楽天/Yahoo!ショッピングを検索しています..."):
        items, errors = search_sources(
            keyword=keyword.strip(),
            min_price=int(min_price),
            max_price=int(max_price),
            hits=int(hits),
            use_rakuten=use_rakuten,
            use_yahoo=use_yahoo,
            rakuten_app_id=rakuten_app_id,
            yahoo_app_id=yahoo_app_id,
        )

    for err in errors:
        st.warning(err)

    if not items:
        st.error("候補が見つかりませんでした。APIキー、価格範囲、キーワードを確認してください。")
        st.stop()

    rows = rank_amazon_fba_candidates(items, config)
    if show_premium_only:
        rows = [
            r for r in rows
            if r["premium_score"] >= config.min_premium_score
            and r["sell_through_score"] >= config.min_sell_through_score
        ]
    summary = summarize_ranked_candidates(rows)
    _render_metric_row(summary)

    df = _prepare_download_df(rows)
    st.download_button(
        "CSVでダウンロード",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="amazon_fba_candidates.csv",
        mime="text/csv",
        use_container_width=True,
    )

    purchase_df = _prepare_purchase_df(rows)
    listing_df = _prepare_amazon_listing_df(rows)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "仕入れ承認リストCSV",
            data=purchase_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="purchase_approval_list.csv",
            mime="text/csv",
            use_container_width=True,
            disabled=purchase_df.empty,
            help="GOかつ売れ残りリスク低の商品だけを、手動仕入れ確認用に出力します。",
        )
    with dl2:
        st.download_button(
            "Amazon出品準備CSV",
            data=listing_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="amazon_listing_draft.csv",
            mime="text/csv",
            use_container_width=True,
            disabled=listing_df.empty,
            help="Amazon出品登録の下書きです。JAN/ASIN/制限確認後にセラーセントラルで調整してください。",
        )

    st.subheader("プレミアム価値・売れやすさ順ランキング")
    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "item_url": st.column_config.LinkColumn("仕入れURL"),
            "amazon_search_url": st.column_config.LinkColumn("Amazon確認"),
            "margin_pct": st.column_config.NumberColumn("利益率%", format="%.1f"),
            "roi_pct": st.column_config.NumberColumn("ROI%", format="%.1f"),
            "premium_score": st.column_config.NumberColumn("プレミアム", format="%.1f"),
            "sell_through_score": st.column_config.NumberColumn("売れやすさ", format="%.1f"),
            "profit_jpy": st.column_config.NumberColumn("利益", format="¥%d"),
        },
    )

    st.subheader("次に確認すること")
    st.markdown(
        "- `GO` は利益率・レビュー条件・簡易リスク語を通過した候補です。\n"
        "- `CHECK` は利益率20%以上ですが、レビュー不足・出品制限リスク語・売れやすさ不足のいずれかがあります。\n"
        "- `inventory_risk=低` かつ `premium_score` と `sell_through_score` が高いものを優先してください。\n"
        "- Amazon側で同一JAN/型番、出品制限、FBA手数料、ランキング、Keepaの月間販売数を確認してください。\n"
        "- 仕入れ実行は `仕入れ承認リストCSV` を見ながら、数量1から手動で始めてください。"
    )

    st.subheader("完全自動化できる範囲")
    st.markdown(
        "- 可能: 楽天/Yahoo!の商品検索、利益計算、プレミアム判定、売れ残りリスク判定、CSV出力。\n"
        "- 条件付きで可能: Amazon SP-APIを使った出品登録・在庫/FBA連携。Amazon大口出品者、SP-API申請、認可が必要です。\n"
        "- 非推奨: 楽天/Yahoo!での自動購入・自動決済。公式購入APIがなく、規約違反や決済情報漏えいのリスクがあります。"
    )
