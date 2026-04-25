"""
モダンUI — Streamlit 向けのテーマ・ヒーロー。
dashboard.py から import する。
"""
from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

# Streamlit コンポーネント向け。インディゴ＋スレート基調
THEME_CSS = """
<style>
  /* 全体 */
  [data-testid="stAppViewContainer"] > .main {
    background: linear-gradient(165deg, #0f172a 0%, #1e1b4b 18%, #f8fafc 18%, #f1f5f9 100%);
  }
  [data-testid="stAppViewBlockContainer"] {
    max-width: 1200px;
    padding: 0.5rem 1.25rem 1.5rem 1.25rem;
  }
  [data-testid="stHeader"] { background: transparent; }

  /* タブ: アンダーライン + 太字 */
  [data-baseweb="tab-list"] {
    gap: 0.25rem;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 0.25rem;
  }
  button[data-baseweb="tab"] {
    border-radius: 0.5rem 0.5rem 0 0 !important;
    font-weight: 600;
    color: #64748b !important;
  }
  [aria-selected="true"] { color: #312e81 !important; }
  [data-baseweb="tab-panel"] { padding-top: 0.75rem; }

  /* サイドバー */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
  }
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] span { color: #e2e8f0; }
  [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: #f8fafc !important;
  }
  [data-testid="stSidebar"] [data-baseweb="select"] > div {
    background-color: #1e293b;
    color: #f1f5f9;
  }
  [data-testid="stSidebar"] [data-baseweb="slider"] { filter: none; }
  [data-testid="stSidebar"] [data-baseweb="input"] {
    background-color: #0f172a;
    color: #f8fafc;
  }

  /* ヒーロー */
  .ux-hero {
    border-radius: 1rem;
    background: linear-gradient(135deg, #312e81 0%, #4c1d95 45%, #5b21b6 100%);
    color: #f8fafc;
    padding: 1.25rem 1.5rem 1.35rem 1.5rem;
    margin: 0 0 0.5rem 0;
    box-shadow: 0 12px 40px -8px rgba(30, 27, 75, 0.45);
  }
  .ux-hero__inner { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 1rem; }
  .ux-hero__eyebrow {
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #c4b5fd;
    margin: 0 0 0.35rem 0;
  }
  .ux-hero__title { font-size: 1.65rem; font-weight: 700; margin: 0; line-height: 1.2; }
  .ux-hero__desc { font-size: 0.92rem; color: #e9d5ff; margin: 0.45rem 0 0 0; max-width: 36rem; }
  .ux-hero__stats { display: flex; flex-wrap: wrap; gap: 0.75rem; }
  .ux-pill {
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    font-size: 0.86rem;
    font-variant-numeric: tabular-nums;
  }
  .ux-pill b { color: #fef08a; }
  @media (max-width: 640px) {
    .ux-hero { padding: 1rem; }
    .ux-hero__title { font-size: 1.35rem; }
  }
</style>
"""


def apply_modern_ui() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def render_modern_hero(usdjpy: float | None) -> None:
    """メイン上段のカード。為替表示はサイドバーと重複可。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if usdjpy is not None and usdjpy > 0:
        rate = html.escape(f"{usdjpy:.2f}")
        rate_pill = f'<span class="ux-pill">USD/JPY <b>{rate}</b></span>'
    else:
        rate_pill = '<span class="ux-pill">USD/JPY <b>—</b></span>'
    t_pill = f'<span class="ux-pill">更新 {html.escape(now)}</span>'
    st.markdown(
        f"""
<div class="ux-hero">
  <div class="ux-hero__inner">
    <div>
      <p class="ux-hero__eyebrow">Export profit intelligence</p>
      <h1 class="ux-hero__title">eBay 輸出 利益判定</h1>
      <p class="ux-hero__desc">送料・関税・為替を一体計算。単品・CSV・仕入れ・相場リサーチまで一画面で。</p>
    </div>
    <div class="ux-hero__stats">
      {rate_pill}
      {t_pill}
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
