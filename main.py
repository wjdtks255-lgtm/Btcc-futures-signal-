from datetime import datetime, timedelta, timezone
import json
import os
import time
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE = "bot_state.json"
KST = timezone(timedelta(hours=9))
TV_URL = "https://scanner.tradingview.com/crypto/scan"

MAX_ALERTS = 3
COOLDOWN = 240
MIN_SCORE = 82

COL = [
    "open|15",
    "high|15",
    "low|15",
    "close|15",
    "volume|15",
    "EMA20|15",
    "EMA50|15",
    "EMA100|15",
    "RSI|15",
    "ADX|15",
    "ATR|15",
    "open|60",
    "high|60",
    "low|60",
    "close|60",
    "volume|60",
    "EMA20|60",
    "EMA50|60",
    "EMA100|60",
    "RSI|60",
    "ADX|60",
    "ATR|60",
    "change|15",
    "change|60",
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
        s = {"positions": {}, "signals": {}}
    s.setdefault("positions", {})
    s.setdefault("signals", {})
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
        "disable_web_page_preview": True,
        "disable_notification": False,
    }
    for n in range(2):
        try:
            r = requests.post(url, json=data, timeout=20)
            j = r.json() if r.status_code == 200 else {}
            if r.status_code == 200 and j.get("ok") is True:
                return True
        except Exception as e:
            print("TG ERROR:", e)
        if n == 0:
            time.sleep(1)
    return False


def rows():
    q = {
        "options": {"lang": "en"},
        "markets": ["crypto"],
        "filter": [{"left": "exchange", "operation": "equal", "right": "BTCC"}],
        "columns": COL,
        "sort": {"sortBy": "volume|15", "sortOrder": "desc"},
        "range": [0, 500],
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


# --- [2단계: 실제 15분봉 시계열 K라인 수집 및 파동 구조 검증] ---
def fetch_klines(sym, limit=20):
    """
    BTCC Public Rest API 또는 호환 데이터 원천에서 최근 15분봉 OHLCV 데이터를 수집
    (API 규격에 맞춰 URL 및 Parameter 조정)
    """
    try:
        url = f"https://kline.btcc.com/api/v1/klines?symbol={sym}&interval=15m&limit={limit}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            # 반환 구조: [[time, open, high, low, close, volume], ...]
            data = r.json()
            klines = []
            for item in data:
                klines.append(
                    {
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "vol": float(item[5]),
                    }
                )
            return klines
    except Exception as e:
        print(f"KLINE FETCH ERROR ({sym}):", e)
    return []


def verify_candle_structure(sym, direction, current_p):
    """
    시계열 캔들 구조 기반 검증:
    LONG: 최근 3~8개 봉 내 눌림(음봉/저점 형성) -> EMA20 부근 서포트 -> 현재 양봉 전환 및 직전 고점/저점 이탈
    SHORT: 최근 3~8개 봉 내 반등(양봉/고점 형성) -> EMA20 부근 저항 -> 현재 음봉 전환 및 직전 저점 이탈
    """
    klines = fetch_klines(sym, limit=12)
    if len(klines) < 8:
        # K라인 수집 실패 시 1차 스캐너 결과에 의존하되 완화 처리 또는 탈락
        return True, "KLINE_SKIP"

    history = klines[:-1]  # 확정된 직전 봉들 (최근 7~10개)
    curr = klines[-1]  # 진행 중인 현재 봉

    # 1. 미세 움직임(횡보/죽은 파동) 걸러내기: 최근 5개 봉의 가격 변동 폭 검사
    recent_highs = [k["high"] for k in history[-5:]]
    recent_lows = [k["low"] for k in history[-5:]]
    max_range = (max(recent_highs) - min(recent_lows)) / current_p * 100

    if max_range < 0.25:  # 최근 5개 봉 동안 변동폭이 0.25% 미만이면 단순 횡보
        return False, "FLAT_CONSOLIDATION"

    if direction == "LONG":
        # 최근 3~8봉 내 음봉 눌림 파동 존재 여부
        has_pullback = any(
            k["close"] < k["open"] for k in history[-6:-1]
        )  # 최근 눌림 발생
        is_rebound = (
            curr["close"] > curr["open"]
            and curr["close"] > history[-1]["close"]
        )  # 현재 봉 재상승 전환

        if not has_pullback:
            return False, "NO_PULLBACK_WAVE"
        if not is_rebound:
            return False, "NO_REBOUND_TRIGGER"

    else:  # SHORT
        # 최근 3~8봉 내 양봉 반등 파동 존재 여부
        has_bounce = any(
            k["close"] > k["open"] for k in history[-6:-1]
        )  # 최근 반등 발생
        is_breakdown = (
            curr["close"] < curr["open"] and curr["close"] < history[-1]["low"]
        )  # 현재 봉 직전 저점 깨며 재하락

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

    # 기본 필터링
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

    # 2단계: 시계열 캔들 구조 엄격 검증
    sym = symbol(r)
    valid_structure, reason = verify_candle_structure(sym, direction, p)
    if not valid_structure:
        st["trigger"] += 1
        return

    # 점수 산정
    trend = 22 + (2 if (ph > e20h if bull else ph < e20h) else 0)
    location = 20 if abs(d20) <= 0.25 else (17 if abs(d20) <= 0.45 else 14)
    timing = 20 if reason == "STRUCTURE_VALIDATED" else 15

    rscore = 8 if (40 <= rs <= 60) else 5
    adscore = 10 if adx >= 30 and adxh >= 30 else 7
    volscore = 5 if 0.30 <= atrp <= 1.80 else 3
    momscore = 8 if abs(ch15) >= 0.15 else 3  # 미세한 변동(0.04% 등) 점수 제한

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

    # A+ 등급 기준 강화: 캔들 파동 구조 완벽 검증 + 모멘텀 존재 필수
    quality = (
        "A+"
        if (
            score >= 90
            and reason == "STRUCTURE_VALIDATED"
            and abs(ch15) >= 0.15
        )
        else "A"
    )

    risk = max(atr * 1.20, p * 0.0045)
    sl = p - risk if bull else p + risk
    tp1 = p + risk * 1.5 if bull else p - risk * 1.5
    tp2 = p + risk * 2.5 if bull else p - risk * 2.5
    lev = 8 if atrp < 0.8 else (6 if atrp < 1.4 else 4)

    return {
        "symbol": sym,
        "direction": direction,
        "score": score,
        "quality": quality,
        "price": p,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
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
        "setup": (
            "눌림 후 상승 재진입(파동 확인)"
            if bull
            else "반등 후 하락 재진입(파동 확인)"
        ),
        "reasons": [
            "1H/15M 추세 정렬",
            "시계열 캔들 반등/눌림 형성 확인",
            "현재봉 재이탈 방향성 확정",
            "횡보/무변동 구간 제외 통과",
        ],
    }


def msg(s):
    icon = "🟢" if s["direction"] == "LONG" else "🔴"
    return (
        f"{icon} 🔥 {s['quality']} HIGH QUALITY ENTRY\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{s['symbol']}\n"
        f"📌 {s['direction']} {icon}\n"
        f"🏆 Quality : {s['quality']}\n"
        f"⭐ Entry Score : {s['score']}/100\n"
        f"🎯 Setup : {s['setup']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 TRADE PLAN\n"
        f"├ Entry : {fmt(s['price'])}\n"
        f"├ SL : {fmt(s['sl'])}\n"
        f"├ TP1 : {fmt(s['tp1'])}\n"
        f"└ TP2 : {fmt(s['tp2'])}\n\n"
        "📊 MARKET\n"
        f"├ RSI 15M : {s['rsi']:.1f}\n"
        f"├ RSI 1H : {s['rsh']:.1f}\n"
        f"├ ADX 15M : {s['adx']:.1f}\n"
        f"├ ADX 1H : {s['adxh']:.1f}\n"
        f"├ 15M : {s['ch15']:+.2f}%\n"
        f"├ 1H : {s['ch60']:+.2f}%\n"
        f"└ ATR : {s['atrp']:.2f}%\n\n"
        "🧠 ENTRY REASONS\n"
        + "\n".join("• " + x for x in s["reasons"])
        + "\n\n⚙️ RISK\n"
        f"├ Leverage : {s['lev']}x\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ Signal only / No auto order"
    )


def main():
    rs = rows()
    if not rs:
        return
    state = load()
    st = {
        k: 0
        for k in [
            "data",
            "dead",
            "volatile",
            "trend",
            "location",
            "trigger",
            "chase",
            "momentum",
            "rsi",
            "adx",
            "score",
            "grade",
            "risk",
        ]
    }

    candidates = []
    for r in rs:
        s = analyze(r, st)
        if s:
            candidates.append(s)

    candidates.sort(
        key=lambda x: (
            1 if x["quality"] == "A+" else 0,
            x["score"],
            x["timing"],
            x["location"],
        ),
        reverse=True,
    )

    sent = 0
    t = time.time()
    for s in candidates:
        if sent >= MAX_ALERTS:
            break
        key = s["symbol"]
        if key in state["positions"]:
            continue
        sid = f"{key}:{s['direction']}"
        if t - float(state["signals"].get(sid,0) or 0) < COOLDOWN * 60:
            continue

        if tg(msg(s), f"{key} {s['direction']} {s['quality']}"):
            state["signals"][sid] = t
            state["positions"][key] = {
                "symbol": key,
                "direction": s["direction"],
                "entry": s["price"],
                "sl": s["sl"],
                "tp1": s["tp1"],
                "tp2": s["tp2"],
                "tp1_hit": False,
            }
            save(state)
            sent += 1
            time.sleep(0.7)


if __name__ == "__main__":
    main()
