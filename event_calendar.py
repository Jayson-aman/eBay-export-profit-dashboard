"""
event_calendar.py — ギフト・ライフイベントに合わせた「出品前倒し」カレンダー

目的: 年度末・年末年始・クリスマス・誕生日・記念日・入学卒業就職など、
      **イベントの何週間前から**需要が立ち上がるかをヒューリスティクスで推定し、
      出品・値付け・在庫のタイミングの参考にする。

※ 宗教・家庭の習慣で大きく変わる。実売上を保証しない。
※ 品目ヒントから **充電器・汎用USBケーブル・モバイルバッテリ等**は意図的に省く（薄利・規制）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional


@dataclass(frozen=True)
class EventTemplate:
    id: str
    name_ja: str
    name_en: str
    # 仕向け先のタグ: "all" | "JP_style" | "US_style" | "EU_style" | 国名
    regions: frozenset[str]
    # 年間の「代表ピーク月」(1-12)。複数イベントは複数回出る
    peak_months: tuple[int, ...]
    # そのイベントに向けて listing を始めるべき **週数前** [min, max]
    list_weeks_before: tuple[int, int]
    # ピーク需要の **週数前** [min, max]（配送・ギフト包装を考慮）
    demand_peak_weeks_before: tuple[int, int]
    # このイベントで売れやすいカテゴリ・品目のヒント（日本からの輸出視点）
    product_hints_ja: tuple[str, ...]
    notes_ja: str


# 地域タグ（「all」は本当に全世界向けイベントのみに使う）
ALL = frozenset({"all"})
JP = frozenset({"JP_style", "日本"})
US = frozenset({"US_style", "アメリカ", "US", "USA", "カナダ", "メキシコ"})
EU = frozenset({
    "EU_style", "イギリス", "UK", "GB", "ドイツ", "フランス", "イタリア",
    "スペイン", "オランダ", "ベルギー", "スイス", "スウェーデン", "EU",
})


EVENTS: tuple[EventTemplate, ...] = (
    EventTemplate(
        id="year_end_gift",
        name_ja="年末・忘年会・御歳暮",
        name_en="Year-end / corporate gifts",
        regions=JP | US | EU,
        peak_months=(11, 12),
        list_weeks_before=(8, 12),
        demand_peak_weeks_before=(2, 5),
        product_hints_ja=(
            "高級お茶・茶器セット", "漆器・箸・キッチン小物", "骨董・工芸ギフト",
            "化粧品セット", "時計・小物", "包装・のし対応できる軽量品",
        ),
        notes_ja="法人・親族への贈答。配送遅延を見て11月中〜12月上旬に需要ピーク。",
    ),
    EventTemplate(
        id="new_year",
        name_ja="年始・お年賀・初売り",
        name_en="New Year",
        regions=JP | US | EU,
        peak_months=(1,),
        list_weeks_before=(4, 8),
        demand_peak_weeks_before=(1, 3),
        product_hints_ja=(
            "縁起物・招き猫・干支グッズ", "お茶・和菓子系ギフト", "新しい趣味のスターターセット",
        ),
        notes_ja="年始は「新規の趣味」「インテリア刷新」も動きやすい。",
    ),
    EventTemplate(
        id="christmas",
        name_ja="クリスマス",
        name_en="Christmas",
        regions=US | EU | frozenset({"オーストラリア"}),
        peak_months=(11, 12),
        list_weeks_before=(6, 10),
        demand_peak_weeks_before=(2, 4),
        product_hints_ja=(
            "オーナメント・装飾", "フィギュア・コレクターズ", "おもちゃ・ゲーム",
            "アパレル小物", "骨董・一点物のギフト", "カメラ・レンズ（趣味）",
        ),
        notes_ja="北米・欧州は11月から検索増。国際配送は最低2〜3週前までに出品・発送を想定。",
    ),
    EventTemplate(
        id="valentine_white",
        name_ja="バレンタイン・ホワイトデー",
        name_en="Valentine / White Day",
        regions=JP | US | EU,
        peak_months=(2, 3),
        list_weeks_before=(5, 8),
        demand_peak_weeks_before=(1, 3),
        product_hints_ja=(
            "スイーツ系は不向きなら雑貨・文具・アクセ・コスメ", "ペアギフト訴求",
        ),
        notes_ja="日本は義理チョコ文化。海外はカップルギフト・ジュエリー寄り。",
    ),
    EventTemplate(
        id="mothers_fathers",
        name_ja="母の日・父の日",
        name_en="Mother's / Father's Day",
        regions=US | EU,
        peak_months=(5, 6),
        list_weeks_before=(5, 8),
        demand_peak_weeks_before=(2, 3),
        product_hints_ja=(
            "包丁・キッチン", "時計", "趣味ギア（父の日）", "化粧品・茶器（母の日）",
        ),
        notes_ja="各国で日付が違う。アメリカ母の日は5月第2日曜など要確認。",
    ),
    EventTemplate(
        id="fiscal_year_end_jp",
        name_ja="年度末（日本・3月）",
        name_en="Japanese fiscal year-end (March)",
        regions=JP,
        peak_months=(2, 3),
        list_weeks_before=(6, 10),
        demand_peak_weeks_before=(2, 5),
        product_hints_ja=(
            "退職・異動の贈答品", "記念品・刻印できる工芸", "新生活向け雑貨",
        ),
        notes_ja="法人予算消化・人事異動。ギフト需要が集中しやすい。",
    ),
    EventTemplate(
        id="graduation_jp",
        name_ja="卒業式（日本・主に3月）",
        name_en="Graduation (Japan March)",
        regions=JP,
        peak_months=(2, 3),
        list_weeks_before=(5, 8),
        demand_peak_weeks_before=(2, 4),
        product_hints_ja=(
            "記念品・名入れ", "制服・袴関連は現地調達多め→一点物・小物で差別化",
            "カメラ・レンズ（記念撮影）",
        ),
        notes_ja="海外需要は少なめだが、在日外国人・逆輸入ニッチはあり。",
    ),
    EventTemplate(
        id="graduation_us",
        name_ja="卒業式（米・5〜6月）",
        name_en="Graduation (US spring)",
        regions=US,
        peak_months=(4, 5, 6),
        list_weeks_before=(6, 10),
        demand_peak_weeks_before=(2, 4),
        product_hints_ja=(
            "ギフト・ジュエリー", "趣味の記念品", "カメラ", "ホビー・フィギュア",
        ),
        notes_ja="地域・大学で時期差あり。春先から検索増。",
    ),
    EventTemplate(
        id="enrollment_jp",
        name_ja="入学（日本・4月）",
        name_en="School enrollment (Japan April)",
        regions=JP,
        peak_months=(3, 4),
        list_weeks_before=(5, 9),
        demand_peak_weeks_before=(2, 4),
        product_hints_ja=(
            "ランドセル以外: 文具・習い事道具", "防災・通学グッズは規格注意",
            "趣味系（新しい部活・サークル）",
        ),
        notes_ja="ランドセル等は現地調達が主。日本製文具・ホビーは海外でも差別化しやすい。",
    ),
    EventTemplate(
        id="back_to_school_us",
        name_ja="新学期・バックトゥスクール（米 8〜9月）",
        name_en="Back to school (US Aug-Sep)",
        regions=US,
        peak_months=(7, 8, 9),
        list_weeks_before=(6, 10),
        demand_peak_weeks_before=(2, 4),
        product_hints_ja=(
            "文具・バッグ", "書籍・画材・実験キット", "ホビー・ゲーム", "スポーツ小物",
        ),
        notes_ja="州によって開校日が異なる。7月中から検索が立ち上がりやすい。"
                 "（汎用充電器・ケーブルは薄利のためヒントから除外）",
    ),
    EventTemplate(
        id="employment_start_jp",
        name_ja="就職・新社会人（日本・主に4月）",
        name_en="New employees (Japan April)",
        regions=JP,
        peak_months=(3, 4),
        list_weeks_before=(5, 9),
        demand_peak_weeks_before=(2, 5),
        product_hints_ja=(
            "時計・カバン・革小物", "ビジネス小物", "趣味のご褒美（転職祝い）",
        ),
        notes_ja="ギフト需要と自分用ご褒美が混在。配送は年度前に間に合わせる。",
    ),
    EventTemplate(
        id="birthday",
        name_ja="誕生日（通年）",
        name_en="Birthdays (year-round)",
        regions=ALL,
        peak_months=tuple(range(1, 13)),
        list_weeks_before=(3, 6),
        demand_peak_weeks_before=(1, 2),
        product_hints_ja=(
            "一点物・コレクション", "ホビー・フィギュア", "ファッション小物",
            "カメラ・ゲーム", "骨董・茶器",
        ),
        notes_ja="通年だが「届くまで2週間」を前提に出品期間を長めに取る。",
    ),
    EventTemplate(
        id="wedding_anniversary",
        name_ja="結婚記念日",
        name_en="Wedding anniversary",
        regions=ALL,
        peak_months=tuple(range(1, 13)),
        list_weeks_before=(4, 8),
        demand_peak_weeks_before=(2, 3),
        product_hints_ja=(
            "ペアで揃う工芸品", "時計", "骨董・一点物", "高級茶器", "アート系",
        ),
        notes_ja="金・銀・パールの年（25/50年等）で検索が立ち上がることも。",
    ),
    EventTemplate(
        id="baby_birth",
        name_ja="出産祝い・命名・初誕生日",
        name_en="Baby birth / shower",
        regions=ALL,
        peak_months=tuple(range(1, 13)),
        list_weeks_before=(6, 12),
        demand_peak_weeks_before=(3, 6),
        product_hints_ja=(
            "出産祝いは現地安全基準の玩具に注意", "命名札・縁起物", "初誕生日用の写真・記念品",
        ),
        notes_ja="ベビー用品は各国の安全規制が厳しい。**玩具・食器は要調査**。工芸・記念品は比較的検討しやすい。",
    ),
)


def _region_tag(destination: str) -> set[str]:
    """仕向け先からイベントの地域フィルタ用タグを推定。"""
    d = destination
    tags: set[str] = {"all"}
    if d in ("アメリカ", "US", "USA", "カナダ", "メキシコ"):
        tags.add("US_style")
    if d in ("イギリス", "UK", "GB", "ドイツ", "フランス", "イタリア", "スペイン",
             "オランダ", "ベルギー", "スイス", "スウェーデン", "EU"):
        tags.add("EU_style")
    if d in ("中国", "韓国", "台湾", "日本"):
        tags.add("JP_style")
    tags.add(d)
    return tags


def _event_applies(ev: EventTemplate, region_tags: set[str]) -> bool:
    if "all" in ev.regions:
        return True
    return bool(region_tags & set(ev.regions))


def _rolling_months(anchor: date, months_ahead: int) -> list[tuple[int, int]]:
    """anchor 月から months_ahead ヶ月先まで (year, month)。"""
    out: list[tuple[int, int]] = []
    y, m = anchor.year, anchor.month
    for _ in range(months_ahead + 1):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def build_listing_calendar(
    destination: str = "アメリカ",
    anchor: Optional[date] = None,
    months_ahead: int = 8,
) -> list[dict[str, Any]]:
    """
    仕向け先に関連するイベントごとに、
    「いつ頃までに出品を始めるとよいか」「何を揃えるか」を返す。
    """
    anchor = anchor or date.today()
    region_tags = _region_tag(destination)
    rows: list[dict[str, Any]] = []

    rolling = _rolling_months(anchor, months_ahead)

    for ev in EVENTS:
        if not _event_applies(ev, region_tags):
            continue
        # 通年イベントは1行にまとめる
        if ev.id in ("birthday", "wedding_anniversary", "baby_birth"):
            w_min, w_max = ev.list_weeks_before
            rows.append({
                "event_id": ev.id,
                "event_name_ja": ev.name_ja,
                "event_name_en": ev.name_en,
                "timing_type": "recurring",
                "list_by_weeks_before": f"{w_min}〜{w_max}週間前から出品開始推奨",
                "demand_peak_weeks_before": (
                    f"{ev.demand_peak_weeks_before[0]}〜"
                    f"{ev.demand_peak_weeks_before[1]}週前に需要ピーク目安"
                ),
                "product_hints_ja": list(ev.product_hints_ja),
                "notes_ja": ev.notes_ja,
                "approx_peak": "通年（日付はバイヤー個別）",
                "list_window_start": "",
                "list_window_end": "",
            })
            continue

        for y, mo in rolling:
            if mo not in ev.peak_months:
                continue
            peak_approx = date(y, mo, 15)
            w_min, w_max = ev.list_weeks_before
            list_start = peak_approx - timedelta(weeks=w_max)
            list_end = peak_approx - timedelta(weeks=w_min)
            if list_end < anchor - timedelta(days=14):
                continue
            rows.append({
                "event_id": ev.id,
                "event_name_ja": ev.name_ja,
                "event_name_en": ev.name_en,
                "timing_type": "seasonal",
                "approx_peak_month": f"{y}年{mo}月頃",
                "approx_peak_date": peak_approx.isoformat(),
                "list_window_start": list_start.isoformat(),
                "list_window_end": list_end.isoformat(),
                "list_by_weeks_before": f"ピークの {w_min}〜{w_max}週間前に出品開始",
                "demand_peak_weeks_before": (
                    f"{ev.demand_peak_weeks_before[0]}〜"
                    f"{ev.demand_peak_weeks_before[1]}週前に検索・購入ピーク目安"
                ),
                "product_hints_ja": list(ev.product_hints_ja),
                "notes_ja": ev.notes_ja,
                "urgency": (
                    "now" if list_start <= anchor <= list_end
                    else ("soon" if anchor < list_start <= anchor + timedelta(weeks=3)
                          else "plan")
                ),
            })

    rows.sort(key=lambda r: (r.get("list_window_start") or "9999", r["event_id"]))
    return rows


def format_listing_calendar_report(
    destination: str,
    anchor: Optional[date] = None,
    months_ahead: int = 8,
) -> str:
    rows = build_listing_calendar(destination, anchor, months_ahead)
    lines = [
        "━" * 62,
        f"  イベント別・出品前倒しカレンダー（仕向け: {destination}）",
        f"  基準日: {anchor or date.today()}",
        "━" * 62,
    ]
    for r in rows[:40]:
        lines.append(f"【{r['event_name_ja']}】")
        if r.get("approx_peak_month"):
            lines.append(f"  需要ピーク目安: {r.get('approx_peak_month', '')}")
        if r.get("list_window_start"):
            lines.append(
                f"  出品ウィンドウ: {r['list_window_start']} 〜 {r['list_window_end']}"
            )
        lines.append(f"  {r.get('list_by_weeks_before', '')}")
        lines.append(f"  品目ヒント: {' / '.join(r['product_hints_ja'][:4])}")
        lines.append("")
    lines.append("━" * 62)
    return "\n".join(lines)


def upcoming_actions(
    destination: str = "アメリカ",
    anchor: Optional[date] = None,
) -> list[str]:
    """今すぐ〜8週以内に「出品を上げる」優先度が高いイベントを短文で。"""
    anchor = anchor or date.today()
    rows = build_listing_calendar(destination, anchor, months_ahead=6)
    urgent: list[str] = []
    for r in rows:
        if r.get("timing_type") == "recurring":
            continue
        ls = r.get("list_window_start")
        le = r.get("list_window_end")
        if not ls or not le:
            continue
        a0 = date.fromisoformat(ls)
        a1 = date.fromisoformat(le)
        if a0 <= anchor <= a1 + timedelta(weeks=2):
            urgent.append(
                f"「{r['event_name_ja']}」— 出品ウィンドウ内〜直後。"
                f" ピーク目安: {r.get('approx_peak_month', '')}"
            )
    if not urgent:
        return ["現在、厳密な「出品ウィンドウ内」のイベントは少ないです。"
                "下表で今後のピークを確認してください。"]
    return urgent
