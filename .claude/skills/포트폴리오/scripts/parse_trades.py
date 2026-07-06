#!/usr/bin/env python3
"""카카오톡 증권사 알림 CSV에서 체결 내역을 추출해 보유종목 현황 JSON을 만든다.

지원 형식:
- NH투자증권: "[NH투자증권] 매수/매도 주문체결 알림" (종 목 명 / 종목코드 / 체결수량 / 체결단가)
- 한국투자증권: "[한국투자증권 체결안내]" (매매구분: 현금매수체결/현금매도체결/매도,
  종목명, 체결수량, 체결단가 — KRW '원' 또는 'USD x')

사용법: python3 parse_trades.py <폴더> [출력.json]
폴더 안의 KakaoTalk_Chat_*.csv 를 전부 읽는다.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

NH_RE = re.compile(
    r"종\s*목\s*명\s*:\s*(?P<name>.+?)\s*\n"
    r"종목코드\s*:\s*(?P<code>\S+)\s*\n"
    r"체결종류\s*:\s*(?P<kind>매수|매도)[^\n]*\n"
    r"체결수량\s*:\s*(?P<qty>[\d,]+)주\s*\n"
    r"체결단가\s*:\s*(?P<price>[\d,]+)원"
)

KIS_RE = re.compile(
    r"매매구분:(?P<kind>현금매수체결|현금매도체결|매도|매수)\s*\n"
    r"\*종목명:(?P<name>[^\n]+)\n"
    r"\*체결수량:(?P<qty>[\d,]+)주\s*\n"
    r"\*체결단가:(?P<cur>USD)?\s*(?P<price>[\d,.]+)원?"
)

KIS_CODE_RE = re.compile(r"^(?P<name>.+?)\((?P<code>[A-Z0-9]{6})\)$")


def parse_csv(path: Path):
    trades = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            msg = row.get("Message", "")
            date = row.get("Date", "")
            for m in NH_RE.finditer(msg):
                trades.append({
                    "date": date,
                    "broker": "NH투자증권",
                    "name": m["name"].strip(),
                    "code": m["code"].strip(),
                    "side": "buy" if m["kind"] == "매수" else "sell",
                    "qty": int(m["qty"].replace(",", "")),
                    "price": float(m["price"].replace(",", "")),
                    "currency": "KRW",
                })
            for m in KIS_RE.finditer(msg):
                name = m["name"].strip()
                code = ""
                cm = KIS_CODE_RE.match(name)
                if cm:
                    name, code = cm["name"].strip(), cm["code"]
                elif "/" in name:  # 예: AAPL/애플
                    code, name = name.split("/", 1)
                trades.append({
                    "date": date,
                    "broker": "한국투자증권",
                    "name": name,
                    "code": code,
                    "side": "buy" if "매수" in m["kind"] else "sell",
                    "qty": int(m["qty"].replace(",", "")),
                    "price": float(m["price"].replace(",", "")),
                    "currency": "USD" if m["cur"] else "KRW",
                })
    return trades


def summarize(trades):
    """평균단가법으로 종목별 보유수량·평단·실현손익 계산."""
    pos = {}
    for t in sorted(trades, key=lambda x: x["date"]):
        key = (t["name"], t["currency"])
        p = pos.setdefault(key, {
            "name": t["name"], "code": t["code"], "currency": t["currency"],
            "brokers": set(), "qty": 0, "avg_price": 0.0,
            "buy_qty": 0, "sell_qty": 0, "realized_pnl": 0.0,
            "first_trade": t["date"], "last_trade": t["date"],
        })
        p["brokers"].add(t["broker"])
        p["last_trade"] = t["date"]
        if t["code"] and not p["code"]:
            p["code"] = t["code"]
        if t["side"] == "buy":
            total_cost = p["avg_price"] * p["qty"] + t["price"] * t["qty"]
            p["qty"] += t["qty"]
            p["buy_qty"] += t["qty"]
            p["avg_price"] = total_cost / p["qty"] if p["qty"] else 0.0
        else:
            sell_qty = min(t["qty"], p["qty"])
            p["realized_pnl"] += (t["price"] - p["avg_price"]) * sell_qty
            p["qty"] -= t["qty"]
            p["sell_qty"] += t["qty"]
            if p["qty"] <= 0:  # 기록 시작 전 보유분 매도 등으로 음수 가능
                p["qty"] = max(p["qty"], 0)
                p["avg_price"] = 0.0
    result = []
    for p in pos.values():
        p["brokers"] = sorted(p["brokers"])
        p["avg_price"] = round(p["avg_price"], 2)
        p["realized_pnl"] = round(p["realized_pnl"], 2)
        result.append(p)
    result.sort(key=lambda x: (-x["qty"], x["name"]))
    return result


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else folder / ".claude" / "data" / "trades.json"
    trades = []
    for csv_path in sorted(folder.glob("KakaoTalk_Chat_*.csv")):
        trades.extend(parse_csv(csv_path))
    # 중복 제거 (같은 알림이 여러 내보내기 파일에 겹칠 수 있음)
    seen, unique = set(), []
    for t in trades:
        k = (t["date"], t["broker"], t["name"], t["side"], t["qty"], t["price"])
        if k not in seen:
            seen.add(k)
            unique.append(t)
    data = {
        "generated_from": [p.name for p in sorted(folder.glob("KakaoTalk_Chat_*.csv"))],
        "trade_count": len(unique),
        "positions": summarize(unique),
        "trades": sorted(unique, key=lambda x: x["date"]),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    held = [p for p in data["positions"] if p["qty"] > 0]
    print(f"체결 {len(unique)}건 파싱 → {out}")
    print(f"보유 종목 {len(held)}개:")
    for p in held:
        cur = "$" if p["currency"] == "USD" else "₩"
        print(f"  {p['name']}: {p['qty']}주 @ {cur}{p['avg_price']:,.0f} (실현손익 {cur}{p['realized_pnl']:,.0f})")
    closed = [p for p in data["positions"] if p["qty"] == 0]
    if closed:
        print(f"청산 종목 {len(closed)}개: " + ", ".join(p["name"] for p in closed))


if __name__ == "__main__":
    main()
