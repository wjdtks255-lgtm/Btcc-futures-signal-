from datetime import datetime, timedelta, timezone
import json
import os
import random
import time
import requests
import ccxt

TOKEN = os.getenv("BTCC_TELEGRAM_TOKEN", "").strip() or os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = (os.getenv("BTCC_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE = "btcc_state.json"
KST = timezone(timedelta(hours=9))

MAX_SLOTS = 5
COOLDOWN = 120
SL_PENALTY_HOURS = 12

# CCXT를 통한 BTCC 선물(Swap) 거래소 연결
exchange = ccxt.btcc({
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})


def now():
    return datetime.now(KST)


def load():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {"positions": {}, "signals": {}, "sl_penalties": {}}
    s.setdefault("positions", {})
    s.setdefault("signals", {})
    s.setdefault("sl_penalties", {})
    return s


def save(s):
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


def tg(msg):
    if not TOKEN or not CHAT_ID:
        print("TG CONFIG ERROR")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    for n in range(3):
        try:
            r = requests.post(url, json=data, timeout=20)
            if r.status_code == 200:
                return True
        except Exception as e:
            print("TG ERROR:", e)
        time.sleep(1.5)
    return False


def get_market_data():
    valid_tickers = []
    try:
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        
        # USDT 퍼페추얼 마켓 필터링
        market_list = []
        for symbol, ticker in tickers.items():
            if '/USDT:USDT' in symbol or ('/USDT' in symbol and exchange.markets[symbol].get('swap', False)):
                market_list.append((symbol, ticker))

        random.shuffle(market_list)
        for symbol, ticker in market_list:
            try:
                last_price = float(ticker.get('last', 0) or 0)
                change = float(ticker.get('percentage', 0) or 0)
                if last_price <= 0:
                    continue
                
                base_symbol = symbol.split('/')[0]
                if "MATIC" in base_symbol:
                    continue

                valid_tickers.append({
                    "symbol": base_symbol,
                    "contract": symbol,
                    "price": last_price,
                    "change": change
                })
            except Exception:
                pass
    except Exception as e:
        print(f"Error fetching BTCC tickers: {e}")

    if not valid_tickers:
        valid_tickers = [
            {"symbol": "BTC", "contract": "BTC/USDT:USDT", "price": 60000.0, "change": 1.5},
            {"symbol": "ETH", "contract": "ETH/USDT:USDT", "price": 3000.0, "change": -0.8},
        ]
    return valid_tickers


def get_recent_high_low(contract):
    try:
        ohlcv = exchange.fetch_ohlcv(contract, timeframe='15m', limit=10)
        if ohlcv and isinstance(ohlcv, list):
            highs = [float(item[2]) for item in ohlcv]
            lows = [float(item[3]) for item in ohlcv]
            closes = [float(item[4]) for item in ohlcv]
            return max(highs), min(lows), closes[-1]
    except Exception as e:
        print(f"Error fetching OHLCV for {contract}: {e}")
    return None, None, None


def fmt(x):
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")


def msg(s, slot_no):
    return (
        f"🚨 *BTCC 프로페셔널 트레이딩 시그널* 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 슬롯 번호: `[ {slot_no} / {MAX_SLOTS} ]`\n"
        f"🪙 종목명: `{s['symbol']} / USDT`\n"
        f"📊 포지션: **{s['pos_text']}**\n"
        f"💰 실시간 진입가: `{fmt(s['price'])}` USDT\n\n"
        f"⚙️ 포지션 운용 가이드\n"
        f"  • 권장 레버리지: `{s['lev']}x` (격리 마진)\n\n"
        f"🎯 목표가 (Take Profit)\n"
        f"  • 1차 (TP1): `{fmt(s['tp1'])}` (본전 스탑)\n"
        f"  • 2차 (TP2): `{fmt(s['tp2'])}`\n"
        f"  • 3차 (TP3): `{fmt(s['tp3'])}` (최종 익절)\n\n"
        f"🛡️ 손절가 (Stop Loss): `{fmt(s['sl'])}`\n"
        f"⏱️ 발생 시간: `{now().strftime('%Y-%m-%d %H:%M:%S')} (KST)`"
    )


def status_msg(positions):
    if not positions:
        return "📊 *[현재 보유 중인 포지션 현황]*\n━━━━━━━━━━━━━━━━━━━━━━\n• 현재 활성화된 포지션이 없습니다. (모든 슬롯 대기 중)"
    
    lines = [
        "📊 *[현재 보유 중인 포지션 현황]*",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, (sym, p) in enumerate(positions.items(), 1):
        d = p.get("direction", "LONG")
        pos_icon = "🟢 롱" if d == "LONG" else "🔴 숏"
        entry = p.get("entry", 0)
        tp1_status = "✅ 도달(본전스탑)" if p.get("tp1_hit") else "⏳ 대기중"
        lines.append(f"• `[{idx}]` **{sym} / USDT** ({pos_icon})\n  - 진입가: `{fmt(entry)}` | TP1: `{tp1_status}`")
    
    lines.append(f"\n⏱️ 확인 시간: `{now().strftime('%m-%d %H:%M')} (KST)`")
    return "\n".join(lines)


def posmsg(p, k):
    sy = p.get("symbol", "UNKNOWN")
    d = p.get("direction", "LONG")
    if k == "TP1":
        return f"🎯 *[TP1 1차 익절 & 본전스탑]*\n🪙 종목: `{sy} / USDT` ({d})\n💰 1차 목표가 도달!\n🛡️ 손절가를 진입가로 상향 조정."
    if k == "TP2":
        return f"🎯 *[TP2 2차 익절 도달]*\n🪙 종목: `{sy} / USDT` ({d})\n💰 2차 목표가 도달!"
    if k == "TP3":
        return f"🎉 *[TP3 최종 익절 달성 마감!]*\n🪙 종목: `{sy} / USDT` ({d})\n🎯 3차 목표가 달성 완료!"
    return f"🛡️ *[손절(SL) 도달 마감]*\n🪙 종목: `{sy} / USDT` ({d})\n📉 손절가 이탈로 포지션 종료 (12시간 재진입 금지)"


def check(state):
    for key, p in list(state["positions"].items()):
        if not isinstance(p, dict):
            state["positions"].pop(key, None)
            continue
        p.setdefault("symbol", key)
        contract = p.get("contract", f"{key}/USDT:USDT")
        
        h, l, curr_p = get_recent_high_low(contract)
        if curr_p is None:
            continue
            
        high_p = h if h else curr_p
        low_p = l if l else curr_p
        long = p["direction"] == "LONG"

        if long:
            if high_p >= p["tp3"]:
                tg(posmsg(p, "TP3"))
                state["positions"].pop(key, None)
                continue
            if low_p <= p["sl"]:
                tg(posmsg(p, "SL"))
                state.setdefault("sl_penalties", {})[key] = time.time()
                state["positions"].pop(key, None)
                continue
            if high_p >= p["tp2"] and "TP2" not in p.get("hit", []):
                tg(posmsg(p, "TP2"))
                p.setdefault("hit", []).append("TP2")
            if not p.get("tp1_hit", False) and high_p >= p["tp1"]:
                p["tp1_hit"] = True
                p["sl"] = p["entry"]
                tg(posmsg(p, "TP1"))
        else:
            if low_p <= p["tp3"]:
                tg(posmsg(p, "TP3"))
                state["positions"].pop(key, None)
                continue
            if high_p >= p["sl"]:
                tg(posmsg(p, "SL"))
                state.setdefault("sl_penalties", {})[key] = time.time()
                state["positions"].pop(key, None)
                continue
            if low_p <= p["tp2"] and "TP2" not in p.get("hit", []):
                tg(posmsg(p, "TP2"))
                p.setdefault("hit", []).append("TP2")
            if not p.get("tp1_hit", False) and low_p <= p["tp1"]:
                p["tp1_hit"] = True
                p["sl"] = p["entry"]
                tg(posmsg(p, "TP1"))


def main():
    print("===================================")
    print(" BTCC DIRECT POSITION MONITOR")
    print("===================================")
    
    state = load()
    
    check(state)
    save(state)

    tg(status_msg(state["positions"]))

    tickers = get_market_data()
    print("Fetched Tickers:", len(tickers))
    if not tickers:
        print("No tickers fetched.")
        return

    candidates = []
    for item in tickers:
        sym = item["symbol"]
        contract = item["contract"]
        p = item["price"]
        ch = item["change"]
        
        direction = "LONG" if ch >= 0 else "SHORT"
        risk = max(p * 0.015, p * 0.005)

        abs_ch = abs(ch)
        if abs_ch > 5.0:
            lev = 3
        elif abs_ch > 2.5:
            lev = 5
        elif abs_ch > 1.0:
            lev = 7
        else:
            lev = 10

        if direction == "LONG":
            sl = p - risk
            tp1 = p + risk * 1.5
            tp2 = p + risk * 2.5
            tp3 = p + risk * 4.0
            pos_text = "롱 (LONG) 🟢"
        else:
            sl = p + risk
            tp1 = p - risk * 1.5
            tp2 = p - risk * 2.5
            tp3 = p - risk * 4.0
            pos_text = "숏 (SHORT) 🔴"

        candidates.append({
            "symbol": sym,
            "contract": contract,
            "direction": direction,
            "price": p,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "lev": lev,
            "pos_text": pos_text,
        })

    random.shuffle(candidates)

    current_active_count = len(state["positions"])
    available_slots = MAX_SLOTS - current_active_count
    print(f"ACTIVE SLOTS: {current_active_count}/{MAX_SLOTS} (Available: {available_slots})")

    sent = 0
    t = time.time()
    sl_penalties = state.get("sl_penalties", {})

    if available_slots > 0:
        for s in candidates:
            if sent >= available_slots:
                break
            key = s["symbol"]

            if key in state["positions"] or key in sl_penalties:
                if key in sl_penalties and t - float(sl_penalties[key]) < SL_PENALTY_HOURS * 3600:
                    continue

            sid = f"{key}:{s['direction']}"
            if t - float(state["signals"].get(sid, 0) or 0) < COOLDOWN * 60:
                continue

            current_slot_number = current_active_count + sent + 1
            if not tg(msg(s, current_slot_number)):
                continue

            state["signals"][sid] = t
            state["positions"][key] = {
                "symbol": key,
                "contract": s["contract"],
                "direction": s["direction"],
                "entry": s["price"],
                "sl": s["sl"],
                "tp1": s["tp1"],
                "tp2": s["tp2"],
                "tp3": s["tp3"],
                "tp1_hit": False,
                "hit": [],
            }
            save(state)
            sent += 1
            print("SIGNAL SENT:", key)

    save(state)
    print("DONE. Sent:", sent)


if __name__ == "__main__":
    main()
