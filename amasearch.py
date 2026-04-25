"""
アマサーチ（店舗せどり向けリサーチアプリ）および Amazon.co.jp 検索の外部リンク用。

アマサーチは https://amasearch.knz-c.com/ が公式。Web API の提供はなく、
本リポジトリからはブラウザ／ストアへの導線のみを提供する。
"""
from __future__ import annotations

from urllib.parse import quote

# 公式・配信
AMASEARCH_OFFICIAL = "https://amasearch.knz-c.com/"
AMASEARCH_GOOGLE_PLAY = (
    "https://play.google.com/store/apps/details?hl=ja&id=com.knzc.app.amasearch"
)
# iOS は App Store 内検索（アプリの数値 ID は未固定のため検索結果へ誘導）
AMASEARCH_APP_STORE_SEARCH = (
    "https://apps.apple.com/jp/search?term="
    "%E3%82%A2%E3%83%9E%E3%82%B5%E3%83%BC%E3%83%81&media=software"
)


def amazon_co_jp_search_url(keyword: str) -> str:
    """Amazon.co.jp のキーワード検索URL（JAN や商品名を渡せる）。"""
    q = (keyword or "").strip()
    return f"https://www.amazon.co.jp/s?k={quote(q, safe='')}"
