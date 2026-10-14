from datetime import datetime, timedelta, timezone
import json
import os
import random
import time
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE = "btcc_state.json"
KST = timezone(timedelta(hours=9))
TV_URL = "https://scanner.tradingview.com/crypto/scan"

MAX_SLOTS = 5
COOLDOWN = 240          # 일반 신호 쿨다운 (4시간)
SL_PENALTY_HOURS = 12   # 손절(SL) 발생 시 재진입 금지 패널티 시간 (12시간)
MIN_SCORE = 82

# 바이낸스와 BTCC 간 티커 명칭 불일치 대응 매핑
SYMBOL_MAP = {
    "1000PEPEUSDT": "PEPEUSDT",
    "1000SHIBUSDT": "SHIBUSDT",
    "1000BONKUSDT": "BONKUSDT",
    "1000FLOKIUSDT": "FLOKIUSDT",
    "1000LUNCUSDT": "LUNCUSDT",
    "1000SATSUSDT": "SATSUSDT",
}

COL = [
    "open|15", "high|15", "low|15", "close|15", "volume|15",
    "EMA20|15", "EMA50|15", "EMA100|15", "RSI|15", "ADX|15", "ATR|15",
    "open|60", "high|60", "low|60", "close|60", "volume|60",
    "EMA20|60", "EMA50|60", "EMA100|60", "RSI|60", "ADX|60", "ATR|60",
    "change|15", "change|60",
]

HEAD = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Content-Type": "application/json",
}


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


def tg(msg, label="MSG"):
    if not TOKEN or not CHAT_ID:
        print("TG CONFIG ERROR")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "disable_notification": False,
    }
    for n in range(3):
        try:
            r = requests.post(url, json=data, timeout=20)
            j = r.json() if r.status_code == 200 else {}
            if r.status_code == 200 and j.get("ok") is True:
                time.sleep(1.2)
                return True
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 3))
                time.sleep(retry_after)
        except Exception as e:
            print("TG ERROR:", e)
        if n < 2:
            time.sleep(1.5)
    return False


def rows():
    q = {
        "options": {"lang": "en"},
        "markets": ["crypto"],
        "filter": [{"left": "exchange", "operation": "equal", "right": "BTCC"}],
        "columns": COL,
        "sort": {"sortBy": "volume|15", "sortOrder": "desc"},
        "range": [0, 1000],
    }
    try:
        r = requests.post(TV_URL, json=q, headers=HEAD, timeout=25)
        return r.json().get("data", []) if r.status_code == 200 else []
    except Exception as e:
        print("TV ERROR:", e)
        return []


def v(r, i):
    try:
        return float(r["d"][i])
    except Exception:
        return 0.0


def symbol(r):
    return str(r.get("s", "")).split(":")[-1].replace(".P", "")


def fmt(x):
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")


def fetch_klines(sym, limit=12):
    try:
        clean_sym = sym.upper().replace(".P", "")
        clean_sym = SYMBOL_MAP.get(clean_sym, clean_sym)

        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={clean_sym}&interval=15m&limit={limit}"
        r = requests.get(url, timeout=4)

        if r.status_code != 200:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_sym}&interval=15m&limit={limit}"
            r = requests.get(url, timeout=4)

        if r.status_code == 200:
            data = r.json()
            return [
                {
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "vol": float(item[5]),
                }
                for item in data
            ]
    except Exception as e:
        print(f"KLINE FETCH ERROR ({sym}):", e)
    return []


def get_recent_high_low(sym):
    klines = fetch_klines(sym, limit=2)
    if klines:
        curr = klines[-1]
        return curr["high"], curr["low"], curr["close"]
    return None, None, None


def verify_candle_structure(sym, direction, current_p):
    klines = fetch_klines(sym, limit=12)
    if len(klines) < 8:
        return True, "KLINE_FETCH_SKIP"

    history = klines[:-1]
    curr = klines[-1]

    recent_highs = [k["high"] for k in history[-5:]]
    recent_lows = [k["low"] for k in history[-5:]]
    max_range = (max(recent_highs) - min(recent_lows)) / current_p * 100

    if max_range < 0.25:
        return False, "FLAT_CONSOLIDATION"

    if direction == "LONG":
        has_pullback = any(k["close"] < k["open"] for k in history[-6:-1])
        is_rebound = (
            curr["close"] > curr["open"]
            and curr["close"] > history[-1]["close"]
        )
        if not has_pullback:
            return False, "NO_PULLBACK_WAVE"
        if not is_rebound:
            return False, "NO_REBOUND_TRIGGER"
    else:
        has_bounce = any(k["close"] > k["open"] for k in history[-6:-1])
        is_breakdown = (
            curr["close"] < curr["open"] and curr["close"] < history[-1]["low"]
        )
        if not has_bounce:
            return False, "NO_BOUNCE_WAVE"
        if not is_breakdown:
            return False, "NO_BREAKDOWN_TRIGGER"

    return True, "STRUCTURE_VALIDATED"


def analyze(r, st):
    p, o, h, l = [v(r, i) for i in (3, 0, 1, 2)]
    e20, e50, e100, rs, adx, atr = [v(r, i) for i in (5, 6, 7, 8, 9, 10)]
    ph, e20h, e50h, e100h, rsh, adxh, atrh = [
        v(r, i) for i in (14, 16, 17, 18, 19, 20, 21)
    ]
    ch15, ch60 = [v(r, i) for i in (22, 23)]

    if min(p, e20, e50, e100, e20h, e50h, e100h, atr, atrh) <= 0:
        st["data"] += 1
        return

    atrp = atr / p * 100
    atrph = atrh / ph * 100
    d20 = (p - e20) / e20 * 100

    if atrp < 0.18 or atrph < 0.15:
        st["dead"] += 1
        return
    if atrp > 3.5 or atrph > 4.5:
        st["volatile"] += 1
        return

    bull = e20h > e50h > e100h and e20 > e50 > e100 and ph > e20h
    bear = e20h < e50h < e100h and e20 < e50 < e100 and ph < e20h

    if not bull and not bear:
        st["trend"] += 1
        return

    direction = "LONG" if bull else "SHORT"

    if direction == "LONG":
        pullback = -0.75 <= d20 <= 0.25
        not_chase = rsh < 67 and rs < 68 and ch15 < 0.70 and d20 < 0.65
        rsi_ok = 34 <= rs <= 67 and 35 <= rsh <= 66
    else:
        pullback = -0.25 <= d20 <= 0.75
        not_chase = rsh > 33 and rs > 32 and ch15 > -0.70 and d20 > -0.65
        rsi_ok = 33 <= rs <= 66 and 34 <= rsh <= 65

    if not pullback:
        st["location"] += 1
        return
    if not not_chase:
        st["chase"] += 1
        return
    if not rsi_ok:
        st["rsi"] += 1
        return
    if adx < 20 or adxh < 18:
        st["adx"] += 1
        return

    sym = symbol(r)
    valid_structure, reason = verify_candle_structure(sym, direction, p)
    if not valid_structure:
        st["trigger"] += 1
        return

    trend = 22 + (2 if (ph > e20h if bull else ph < e20h) else 0)
    location = 20 if abs(d20) <= 0.25 else (17 if abs(d20) <= 0.45 else 14)
    timing = 23 if reason == "STRUCTURE_VALIDATED" else 15

    rscore = 8 if (40 <= rs <= 60) else 5
    adscore = 10 if adx >= 30 and adxh >= 30 else 7
    volscore = 5 if 0.30 <= atrp <= 1.80 else 3
    momscore = 8 if abs(ch15) >= 0.15 else 3

    penalty = 0
    if bull and (d20 > 0.40 or ch15 > 0.45):
        penalty += 5
    elif not bull and (d20 < -0.40 or ch15 < -0.45):
        penalty += 5

    score = min(
        trend
        + location
        + timing
        + rscore
        + adscore
        + volscore
        + momscore
        - penalty,
        97,
    )

    if score < MIN_SCORE:
        st["score"] += 1
        return

    quality = (
        "A+"
        if (
            score >= 90
            and reason == "STRUCTURE_VALIDATED"
            and abs(ch15) >= 0.15
        )
        else "A"
    )

    if quality == "A" and score < 85:
        st["grade"] += 1
        return

    risk = max(atr * 1.20, p * 0.0045)
    riskpct = risk / p * 100
    if riskpct < 0.35 or riskpct > 3:
        st["risk"] += 1
        return

    if direction == "LONG":
        sl = p - risk
        tp1 = p + risk * 1.5
        tp2 = p + risk * 2.5
        tp3 = p + risk * 4.0
        setup = "눌림 후 상승 재진입(파동 확인)"
        pos_text = "롱 (LONG) 🟢"
    else:
        sl = p + risk
        tp1 = p - risk * 1.5
        tp2 = p - risk * 2.5
        tp3 = p - risk * 4.0
        setup = "반등 후 하락 재진입(파동 확인)"
        pos_text = "숏 (SHORT) 🔴"

    lev = 8 if atrp < 0.8 else (6 if atrp < 1.4 else 4 if atrp < 2 else 3)

    reasons = [
        "1H/15M 추세 정렬",
        "시계열 캔들 반등/눌림 파동 확인",
        "현재봉 재이탈 방향성 확정",
        "횡보/무변동 구간 제외 통과",
    ]

    return {
        "symbol": sym,
        "direction": direction,
        "score": score,
        "quality": quality,
        "price": p,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": rs,
        "rsh": rsh,
        "adx": adx,
        "adxh": adxh,
        "ch15": ch15,
        "ch60": ch60,
        "atrp": atrp,
        "trend": trend,
        "location": location,
        "timing": timing,
        "rscore": rscore,
        "adscore": adscore,
        "momscore": momscore,
        "volscore": volscore,
        "penalty": penalty,
        "lev": lev,
        "setup": setup,
        "reasons": reasons,
        "pos_text": pos_text,
    }


def msg(s, slot_no):
    tv_chart_url = f"https://www.tradingview.com/chart/?symbol=BTCC:{s['symbol']}.P"
    return (
        f"🚨 *BTCC 프로페셔널 트레이딩 시그널* 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 슬롯 번호: `[ {slot_no} / {MAX_SLOTS} ]`\n"
        f"🪙 종목명: `#{s['symbol']}` | 🏆 `{s['quality']}` (Score: {s['score']})\n"
        f"📊 포지션: **{s['pos_text']}**\n"
        f"🎯 진입 셋업: {s['setup']}\n\n"
        f"💰 **TRADE PLAN**\n"
        f"├ Entry : `{fmt(s['price'])}`\n"
        f"├ SL : `{fmt(s['sl'])}`\n"
        f"├ TP1 : `{fmt(s['tp1'])}` (본전 스탑)\n"
        f"├ TP2 : `{fmt(s['tp2'])}`\n"
        f"└ TP3 : `{fmt(s['tp3'])}` (최종 익절)\n\n"
        f"📊 **MARKET & QUALITY**\n"
        f"├ RSI 15M/1H : `{s['rsi']:.1f}` / `{s['rsh']:.1f}`\n"
        f"├ ADX 15M/1H : `{s['adx']:.1f}` / `{s['adxh']:.1f}`\n"
        f"├ 변동률 15M/1H : `{s['ch15']:+.2f}%` / `{s['ch60']:+.2f}%`\n"
        f"└ ATR : `{s['atrp']:.2f}%` | 레버리지: `{s['lev']}x`\n\n"
        f"🔗 [트레이딩뷰 차트 보기]({tv_chart_url})\n"
        f"⚠️ Signal only / No auto order"
    )


def status_msg(positions):
    if not positions:
        return "📊 *[현재 보유 중인 BTCC 포지션 현황]*\n━━━━━━━━━━━━━━━━━━━━━━\n• 현재 활성화된 포지션이 없습니다. (모든 슬롯 대기 중)"
    
    lines = [
        "📊 *[현재 보유 중인 BTCC 포지션 현황]*",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for idx, (sym, p) in enumerate(positions.items(), 1):
        d = p.get("direction", "LONG")
        pos_icon = "🟢 롱" if d == "LONG" else "🔴 숏"
        entry = p.get("entry", 0)
        tp1_status = "✅ 도달(본전스탑)" if p.get("tp1_hit") else "⏳ 대기중"
        lines.append(f"• `[{idx}]` **#{sym}** ({pos_icon})\n  - 진입가: `{fmt(entry)}` | TP1: `{tp1_status}`")
    
    lines.append(f"\n⏱️ 확인 시간: `{now().strftime('%m-%d %H:%M')} (KST)`")
    return "\n".join(lines)


def posmsg(p, k):
    sy = p.get("symbol", "UNKNOWN")
    d = p.get("direction", "LONG")
    if k == "TP1":
        return f"🎯 *[TP1 1차 익절 & 본전스탑]*\n🪙 종목: `#{sy}` ({d})\n💰 1차 목표가 도달!\n🛡️ 손절가를 진입가로 상향 조정."
    if k == "TP2":
        return f"🎯 *[TP2 2차 익절 도달]*\n🪙 종목: `#{sy}` ({d})\n💰 2차 목표가 도달!"
    if k == "TP3":
        return f"🎉 *[TP3 최종 익절 달성 마감!]*\n🪙 종목: `#{sy}` ({d})\n🎯 3차 목표가 달성 완료!"
    return f"🛡️ *[손절(SL) 도달 마감]*\n🪙 종목: `#{sy}` ({d})\n📉 손절가 이탈로 포지션 종료 (12시간 재진입 금지)"


def check(state):
    for key, p in list(state["positions"].items()):
        if not isinstance(p, dict):
            state["positions"].pop(key, None)
            continue
        p.setdefault("symbol", key)
        
        h, l, curr_p = get_recent_high_low(p["symbol"])
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
    print(" BTCC DIRECT POSITION MONITOR + BOT")
    print("===================================")
    print("KST:", now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    state = load()
    check(state)
    save(state)

    tg(status_msg(state["positions"]))

    rs = rows()
    print("BTCC REAL ROWS:", len(rs))
    if not rs:
        tg("⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패", "DATA ERROR")
        return

    st = {
        k: 0
        for k in [
            "data", "dead", "volatile", "trend", "location",
            "trigger", "chase", "momentum", "rsi", "adx", "score", "grade", "risk",
        ]
    }

    candidates = []
    for r in rs:
        try:
            s = analyze(r, st)
            if s:
                candidates.append(s)
        except Exception as e:
            st["data"] += 1
            print("ANALYZE ERROR:", e)

    candidates.sort(
        key=lambda x: (
            1 if x["quality"] == "A+" else 0,
            x["score"],
            x["timing"],
            x["location"],
        ),
        reverse=True,
    )

    print("QUALIFIED:", len(candidates))
    print("FILTER STATS:", st)

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

            if key in state["positions"]:
                print("SKIP ACTIVE:", key)
                continue

            if key in sl_penalties:
                elapsed = t - float(sl_penalties[key])
                if elapsed < SL_PENALTY_HOURS * 3600:
                    print(f"SKIP SL PENALTY ({key}): {int((SL_PENALTY_HOURS * 3600 - elapsed) / 60)}m remaining")
                    continue

            sid = f"{key}:{s['direction']}"
            if t - float(state["signals"].get(sid, 0) or 0) < COOLDOWN * 60:
                print("SKIP COOLDOWN:", key)
                continue

            current_slot_number = current_active_count + sent + 1
            if not tg(msg(s, current_slot_number), f"{key} {s['direction']} {s['quality']}"):
                print("SEND FAILED:", key)
                continue

            state["signals"][sid] = t
            state["positions"][key] = {
                "symbol": key,
                "direction": s["direction"],
                "entry": s["price"],
                "sl": s["sl"],
                "tp1": s["tp1"],
                "tp2": s["tp2"],
                "tp3": s["tp3"],
                "tp1_hit": False,
                "hit": [],
                "score": s["score"],
                "quality": s["quality"],
                "entry_time": now().isoformat(),
            }
            save(state)
            sent += 1
            print("SIGNAL SENT (Slot Filled):", key, s["quality"], s["score"])
    else:
        print("ALL SLOTS FULL (5/5). Skipping new entry scans until a slot frees up.")

    save(state)
    print("FINAL NEW SIGNALS SENT:", sent)
    print("ACTIVE SLOTS NOW:", len(state["positions"]))
    print("DONE")


if __name__ == "__main__":
    main()
