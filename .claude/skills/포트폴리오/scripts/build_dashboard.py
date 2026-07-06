#!/usr/bin/env python3
"""trades.json + image_analysis.json 을 결합해 통합분석 대시보드(통합분석.html)를 생성한다.

사용법: python3 build_dashboard.py <폴더>
  <폴더>/.claude/data/trades.json          (parse_trades.py 산출물)
  <폴더>/.claude/data/image_analysis.json  (AI 분석 이미지 판독 결과)
→ <폴더>/통합분석.html
"""
import json
import sys
from datetime import date
from pathlib import Path

FOLDER = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
DATA = FOLDER / ".claude" / "data"
OUT = FOLDER / "통합분석.html"

trades = json.loads((DATA / "trades.json").read_text(encoding="utf-8"))
imgs = json.loads((DATA / "image_analysis.json").read_text(encoding="utf-8"))

positions = [p for p in trades["positions"] if p["qty"] > 0]
closed = [p for p in trades["positions"] if p["qty"] == 0]
latest = imgs.get("latest_by_stock", {})
images = imgs.get("images", {})


def won(v, signed=False):
    s = f"{abs(v):,.0f}"
    if signed:
        return ("+" if v > 0 else "−" if v < 0 else "") + s
    return s


def pct(v):
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.2f}%"


# ── 종목별 지표 결합 ───────────────────────────────────────────────
rows = []
for p in positions:
    a = images.get(latest.get(p["name"], ""), None)
    cur = a["price"] if a else None
    cost = p["avg_price"] * p["qty"]
    ev = (cur - p["avg_price"]) * p["qty"] if cur else None
    evp = (cur / p["avg_price"] - 1) * 100 if cur and p["avg_price"] else None
    rows.append({**p, "analysis": a, "cur": cur, "cost": cost, "ev": ev, "evp": evp,
                 "img_file": latest.get(p["name"], "")})

total_cost = sum(r["cost"] for r in rows if r["currency"] == "KRW")
total_ev = sum(r["ev"] for r in rows if r["ev"] is not None)
eval_cost = sum(r["cost"] for r in rows if r["ev"] is not None)
total_realized = sum(p["realized_pnl"] for p in trades["positions"] if p["currency"] == "KRW")
analyzed = [r for r in rows if r["ev"] is not None]
missing = [r for r in rows if r["ev"] is None]

# ── 손익률 다이버징 바 ─────────────────────────────────────────────
bar_rows = sorted(analyzed, key=lambda r: -r["evp"])
max_abs = max(abs(r["evp"]) for r in bar_rows) if bar_rows else 1


def bar_html(r):
    w = abs(r["evp"]) / max_abs * 50  # 반폭 50%
    cls = "gain" if r["evp"] >= 0 else "loss"
    side = "left:50%" if r["evp"] >= 0 else f"left:{50 - w:.2f}%"
    lbl_side = "bar-lbl-r" if r["evp"] >= 0 else "bar-lbl-l"
    tip = f"{r['name']} 평단 {won(r['avg_price'])} → 현재 {won(r['cur'])} / 평가손익 {won(r['ev'], True)}원"
    return f"""
      <div class="bar-row" data-tip="{tip}">
        <div class="bar-name">{r['name']}</div>
        <div class="bar-track">
          <div class="bar-mid"></div>
          <div class="bar {cls}" style="{side};width:{w:.2f}%"></div>
          <div class="bar-lbl {lbl_side}" style="{'left:calc(50% + ' + f'{w:.2f}' + '% + 6px)' if r['evp'] >= 0 else 'right:calc(50% + ' + f'{w:.2f}' + '% + 6px)'}">{pct(r['evp'])}</div>
        </div>
      </div>"""


# ── 가격 범위 스트립 (지지·저항·평단·현재가) ─────────────────────────
def strip_html(r):
    a = r["analysis"]
    sup = a.get("support", [])
    res = a.get("resistance", [])
    pts = sup + res + [r["cur"], r["avg_price"]]
    lo, hi = min(pts) * 0.985, max(pts) * 1.015
    span = hi - lo

    def x(v):
        return (v - lo) / span * 100

    tick_items = sorted(
        [(x(v), f"지지{i + 1}", v) for i, v in enumerate(sup)]
        + [(x(v), f"저항{i + 1}", v) for i, v in enumerate(res)])
    ticks, prev_x, prev_low = "", -100.0, False
    for tx, lbl, v in tick_items:
        low = (tx - prev_x < 12) and not prev_low  # 이웃과 가까우면 라벨을 한 단 아래로
        cls = "tick-lbl tick-lbl-low" if low else "tick-lbl"
        ticks += f'<div class="tick" style="left:{tx:.2f}%"><span class="{cls}">{lbl}<br>{won(v)}</span></div>'
        prev_x, prev_low = tx, low
    stop = ""
    strategy = a.get("strategy") or {}
    return f"""
      <div class="strip">
        <div class="strip-track"></div>
        {ticks}{stop}
        <div class="dot avg" style="left:{x(r['avg_price']):.2f}%" data-tip="평균단가 {won(r['avg_price'])}원"><span class="dot-lbl">평단 {won(r['avg_price'])}</span></div>
        <div class="dot cur {'gain' if (r['evp'] or 0) >= 0 else 'loss'}" style="left:{x(r['cur']):.2f}%" data-tip="현재가 {won(r['cur'])}원"><span class="dot-lbl dot-lbl-top">현재 {won(r['cur'])}</span></div>
      </div>"""


def card_html(r):
    a = r["analysis"]
    head = f"""
      <div class="card-head">
        <div><span class="stock-name">{r['name']}</span> <span class="stock-code">{r['code']}</span></div>
        <div class="stock-pnl {'gain' if (r['evp'] or 0) >= 0 else 'loss'}">{pct(r['evp']) if r['evp'] is not None else '—'}</div>
      </div>
      <div class="card-sub">{r['qty']}주 · 평단 {won(r['avg_price'])}원 · 매입 {won(r['cost'])}원 · 평가손익 <b class="{'gain' if (r['ev'] or 0) >= 0 else 'loss'}">{won(r['ev'], True) if r['ev'] is not None else '—'}원</b></div>"""
    strategy = a.get("strategy") if a else None
    comment = a.get("comment") if a else None
    body = strip_html(r)
    items = ""
    if strategy:
        items += "".join(
            f'<div class="strat"><span class="strat-tag strat-{k}">{lbl}</span><span>{strategy[k]}</span></div>'
            for k, lbl in (("buy", "매수"), ("sell", "매도"), ("stop", "손절")) if strategy.get(k))
    if comment:
        items += f'<div class="strat"><span class="strat-tag strat-note">요약</span><span>{comment}</span></div>'
    src = f'<div class="card-src">분석 기준: {a["peak_ref"]} · {r["img_file"]}</div>' if a else ""
    return f'<div class="card">{head}{body}<div class="strats">{items}</div>{src}</div>'


def card_missing(r):
    return f"""
      <div class="card card-dim">
        <div class="card-head"><div><span class="stock-name">{r['name']}</span> <span class="stock-code">{r['code']}</span></div><div class="stock-pnl">—</div></div>
        <div class="card-sub">{r['qty']}주 · 평단 {won(r['avg_price'])}원 · 매입 {won(r['cost'])}원 · 실현손익 {won(r['realized_pnl'], True)}원</div>
        <div class="strat"><span class="strat-tag strat-note">안내</span><span>차트분석 AI 캡처가 없어 현재가·지지/저항 정보가 없습니다. NH 차트분석 AI 화면을 캡처해 이 폴더에 넣고 스킬을 재실행하세요.</span></div>
      </div>"""


table_rows = "".join(
    f"""<tr><td>{r['name']}</td><td>{r['code']}</td><td>{'·'.join(r['brokers'])}</td>
    <td class="num">{r['qty']:,}</td><td class="num">{won(r['avg_price'])}</td>
    <td class="num">{won(r['cur']) if r['cur'] else '—'}</td>
    <td class="num {'gain' if (r['ev'] or 0) > 0 else 'loss' if (r['ev'] or 0) < 0 else ''}">{won(r['ev'], True) if r['ev'] is not None else '—'}</td>
    <td class="num {'gain' if (r['evp'] or 0) > 0 else 'loss' if (r['evp'] or 0) < 0 else ''}">{pct(r['evp']) if r['evp'] is not None else '—'}</td>
    <td class="num">{won(r['realized_pnl'], True)}</td></tr>"""
    for r in rows)

closed_note = ""
if closed:
    parts = []
    for p in closed:
        detail = ", 매수기록 없음" if p["buy_qty"] == 0 else ", 실현 " + won(p["realized_pnl"], True)
        parts.append(f"{p['name']}({p['sell_qty']}주 매도{detail})")
    closed_note = f'<p class="note">청산·기록불완전 종목: {", ".join(parts)}</p>'

html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>보유종목 통합분석</title>
<style>
:root {{
  --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --gain:#d03b3b; --loss:#2a78d6; --accent:#2a78d6; --warn:#ec835a;
}}
@media (prefers-color-scheme: dark) {{ :root {{
  --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --gain:#e66767; --loss:#3987e5; --accent:#3987e5; --warn:#ec835a;
}} }}
* {{ box-sizing:border-box; margin:0 }}
body {{ font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--page); color:var(--ink);
  padding:24px; max-width:1100px; margin:0 auto; line-height:1.5 }}
h1 {{ font-size:22px; font-weight:700 }}
.meta {{ color:var(--muted); font-size:13px; margin:4px 0 20px }}
.gain {{ color:var(--gain) }} .loss {{ color:var(--loss) }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:24px }}
.kpi {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 16px }}
.kpi-l {{ font-size:13px; color:var(--ink2) }}
.kpi-v {{ font-size:26px; font-weight:600; margin-top:2px }}
.kpi-s {{ font-size:12px; color:var(--muted); margin-top:2px }}
.panel {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:18px; margin-bottom:24px }}
.panel h2 {{ font-size:15px; font-weight:600; margin-bottom:4px }}
.panel .desc {{ font-size:12.5px; color:var(--muted); margin-bottom:14px }}
.legend {{ display:flex; gap:16px; font-size:12.5px; color:var(--ink2); margin-bottom:10px }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px }}
.bar-row {{ display:grid; grid-template-columns:190px 1fr; align-items:center; gap:10px; padding:5px 0; position:relative }}
.bar-name {{ font-size:13.5px; text-align:right; color:var(--ink2) }}
.bar-track {{ position:relative; height:22px }}
.bar-mid {{ position:absolute; left:50%; top:-4px; bottom:-4px; width:1px; background:var(--axis) }}
.bar {{ position:absolute; top:2px; height:18px; max-height:18px }}
.bar.gain {{ background:var(--gain); border-radius:0 4px 4px 0 }}
.bar.loss {{ background:var(--loss); border-radius:4px 0 0 4px }}
.bar-lbl {{ position:absolute; top:2px; font-size:12px; color:var(--ink2); white-space:nowrap }}
[data-tip] {{ cursor:default }}
[data-tip]:hover::after {{ content:attr(data-tip); position:absolute; left:50%; bottom:100%; transform:translateX(-50%);
  background:var(--ink); color:var(--surface); font-size:12px; padding:5px 9px; border-radius:6px; white-space:nowrap; z-index:9 }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(460px,1fr)); gap:14px; margin-bottom:24px }}
@media (max-width:520px) {{ .cards {{ grid-template-columns:1fr }} }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px 18px }}
.card-dim {{ opacity:.85 }}
.card-head {{ display:flex; justify-content:space-between; align-items:baseline }}
.stock-name {{ font-size:16px; font-weight:700 }}
.stock-code {{ font-size:12px; color:var(--muted) }}
.stock-pnl {{ font-size:17px; font-weight:700 }}
.card-sub {{ font-size:13px; color:var(--ink2); margin:2px 0 6px }}
.strip {{ position:relative; height:116px; margin:26px 8px 0 }}
.strip-track {{ position:absolute; left:0; right:0; top:34px; height:1px; background:var(--axis) }}
.tick {{ position:absolute; top:28px; width:1px; height:13px; background:var(--muted) }}
.tick-lbl {{ position:absolute; top:32px; left:50%; transform:translateX(-50%); font-size:10.5px; color:var(--muted);
  text-align:center; line-height:1.25; white-space:nowrap }}
.tick-lbl-low {{ top:60px }}
.dot {{ position:absolute; top:34px; width:10px; height:10px; border-radius:50%; transform:translate(-50%,-50%);
  box-shadow:0 0 0 2px var(--surface) }}
.dot.avg {{ background:var(--surface); border:2px solid var(--muted) }}
.dot.cur.gain {{ background:var(--gain) }} .dot.cur.loss {{ background:var(--loss) }}
.dot-lbl {{ position:absolute; top:10px; left:50%; transform:translateX(-50%); font-size:11px; color:var(--ink2); white-space:nowrap }}
.dot-lbl-top {{ top:auto; bottom:14px; font-weight:600; color:var(--ink) }}
.strats {{ margin-top:10px; display:flex; flex-direction:column; gap:6px }}
.strat {{ display:flex; gap:8px; font-size:13px; color:var(--ink2); align-items:flex-start }}
.strat-tag {{ flex:0 0 auto; font-size:11px; font-weight:600; padding:1px 7px; border-radius:99px; border:1px solid var(--border); margin-top:2px }}
.strat-buy {{ color:var(--gain) }} .strat-sell {{ color:var(--loss) }} .strat-stop {{ color:var(--warn) }} .strat-note {{ color:var(--muted) }}
.card-src {{ font-size:11px; color:var(--muted); margin-top:10px }}
table {{ width:100%; border-collapse:collapse; font-size:13px }}
th {{ text-align:left; color:var(--muted); font-weight:500; border-bottom:1px solid var(--grid); padding:6px 8px }}
td {{ border-bottom:1px solid var(--grid); padding:6px 8px }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums }}
.note {{ font-size:12.5px; color:var(--muted); margin-top:10px }}
footer {{ font-size:12px; color:var(--muted); margin-top:8px }}
</style></head><body>
<h1>보유종목 통합분석</h1>
<p class="meta">생성일 {date.today().isoformat()} · 체결 {trades['trade_count']}건 ({', '.join(trades['generated_from'])}) · 현재가는 NH 차트분석 AI 캡처 시점 기준</p>

<div class="kpis">
  <div class="kpi"><div class="kpi-l">보유 종목</div><div class="kpi-v">{len(rows)}개</div><div class="kpi-s">분석 이미지 보유 {len(analyzed)}개 / 미보유 {len(missing)}개</div></div>
  <div class="kpi"><div class="kpi-l">총 매입금액 (보유분)</div><div class="kpi-v">{won(total_cost)}원</div></div>
  <div class="kpi"><div class="kpi-l">평가손익 (분석가능 {len(analyzed)}종목)</div><div class="kpi-v {'gain' if total_ev >= 0 else 'loss'}">{won(total_ev, True)}원</div><div class="kpi-s">매입 {won(eval_cost)}원 대비 {pct(total_ev / eval_cost * 100) if eval_cost else '—'}</div></div>
  <div class="kpi"><div class="kpi-l">실현손익 누계</div><div class="kpi-v {'gain' if total_realized >= 0 else 'loss'}">{won(total_realized, True)}원</div></div>
</div>

<div class="panel">
  <h2>종목별 평가손익률</h2>
  <p class="desc">평균단가 대비 최근 분석 이미지의 현재가 기준</p>
  <div class="legend"><span><i style="background:var(--gain)"></i>수익</span><span><i style="background:var(--loss)"></i>손실</span></div>
  {''.join(bar_html(r) for r in bar_rows)}
</div>

<div class="cards">
{''.join(card_html(r) for r in analyzed)}
{''.join(card_missing(r) for r in missing)}
</div>

<div class="panel">
  <h2>전체 보유내역</h2>
  <p class="desc">평균단가법 기준. 실현손익은 매도분에 대한 누계.</p>
  <table><thead><tr><th>종목</th><th>코드</th><th>증권사</th><th class="num">보유</th><th class="num">평단(원)</th><th class="num">현재가</th><th class="num">평가손익</th><th class="num">손익률</th><th class="num">실현손익</th></tr></thead>
  <tbody>{table_rows}</tbody></table>
  {closed_note}
</div>

<footer>업데이트: 새 체결 CSV·분석 이미지를 이 폴더에 넣고 Claude Code에서 <b>/포트폴리오</b> 실행 → 이 파일이 다시 생성됩니다.</footer>
</body></html>
"""
OUT.write_text(html, encoding="utf-8")
print(f"대시보드 생성 완료 → {OUT}")
print(f"  보유 {len(rows)}종목 (분석 {len(analyzed)} / 이미지없음 {len(missing)})")
print(f"  평가손익 {won(total_ev, True)}원, 실현손익 {won(total_realized, True)}원")
