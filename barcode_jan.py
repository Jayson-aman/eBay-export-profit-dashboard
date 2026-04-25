"""
JAN / EAN / UPC（商品バーコード）の正規化と、国内モール上の価格候補取得。

補足:
  楽天・Yahoo!ショッピングの「商品検索」はキーワード検索です。
  数字をキーワードにすると、多くの商品はタイトルに JAN を載せているためヒットしやすい一方、
  掲載がない品は0件のことがあります（専用のJAN解決 API は未使用）。
"""
from __future__ import annotations

import re
from typing import Any

# JAN=日本で振られる EAN-13 のうち先頭 49/45 等、ただし一般に 8,12,13 桁数値は検索に使用


def normalize_product_barcode(raw: str) -> tuple[str | None, str]:
    """
    入力を数字のみのコードに揃える。
    Returns: (code or None, user-facing error or "")
    """
    if raw is None or not str(raw).strip():
        return None, "バーコード（数字）を入力してください"
    w = re.sub(r"\D", "", str(raw).strip())
    if not w:
        return None, "数字を含めてください（JAN 例: 13桁）"
    if len(w) < 8:
        return None, f"短すぎます（{len(w)} 桁）。8〜13 桁（EAN-8 / UPC / EAN-13 等）"
    if len(w) == 8:
        return w, ""
    if len(w) == 12 or len(w) == 13:
        return w, ""
    if 9 <= len(w) <= 11:
        return None, f"{len(w)} 桁のコードは想定外です。12桁（UPC）または 13 桁（EAN/JAN）に揃えてください"
    return None, f"長すぎます（{len(w)} 桁）。最大 13 桁です"


def search_rakuten_yahoo_shopping(
    code: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    楽天・Yahoo!S で keyword=code として検索し、1列のリストにマージ（source 列で区別）。

    Returns:
        (items, per_source_error_messages) — 件数0でもエラー文が入る場合あり
    """
    from rakuten_search import search as rken_search
    from yahoo_shopping_search import search as yh_search

    rows: list[dict[str, Any]] = []
    errs: list[str] = []
    # 楽天
    try:
        for it in rken_search(keyword=code, hits=20):
            it = dict(it)
            it["lookup_type"] = "キーワード=バーコード"
            it["code_searched"] = code
            rows.append(it)
    except Exception as e:  # noqa: BLE001
        errs.append(f"楽天: {e}")
    # Yahoo!ショッピング
    try:
        for it in yh_search(keyword=code, hits=20):
            it = dict(it)
            it["lookup_type"] = "キーワード=バーコード"
            it["code_searched"] = code
            rows.append(it)
    except Exception as e:  # noqa: BLE001
        errs.append(f"Yahoo!ショッピング: {e}")
    return rows, errs
