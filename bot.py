# BTCC FUTURES SMART SIGNAL BOT (Strict State & Multi-Slot Engine)
import os, json, time, requests, yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta

V = "20.1.4"; STATE = "bot_state.json"; LOG = "bot_log.json"
TOKEN = os.getenv("TELEGRAM_TOKEN", ""); CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
KST = timezone(timedelta(hours=9))

SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"]
MAX_SLOTS = 5

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer): return int(obj)
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.ndarray): return obj.tolist()
        if isinstance(obj, (np.bool_, bool)): return bool(obj)
        return super(NpEncoder, self).default(obj)

def now():
    return datetime.now(KST)

def ts():
    return now().strftime("%Y-%m-%d %H:%M:%S")

def m(x):
    try:
        val = float(x)
        if np.isnan(val) or np.isinf(val): return "$0.00"
        return f"${val:,.4f}" if val < 1 else f"${val:,.2f}"
    except:
        return "$0.00"

def save(p, x):
    q = p + ".tmp"
    with open(q, "w", encoding="utf8") as f:
        json.dump(x, f, ensure_ascii=False, indent=2, cls=NpEncoder)
    os.replace(q, p)

def load(p, d):
    try:
        with open(p, encoding="utf8") as f: return json.load(f)
    except: return d

def tg(x):
    if not TOKEN or not CHAT: 
        print("[TG CONFIG ERROR] Token or Chat ID is missing.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT, "text": x, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15)
        print("[TELEGRAM]", "SENT" if r.ok else f"FAIL: {r.text}")
        return r.ok
    except Exception as e:
        print("[TG ERROR]", e)
        return False

def get_state():
    s = load(STATE, {"positions": []})
    if not isinstance(s, dict) or "positions" not in s:
        s = {"positions": []}
    return s

def clean(x):
    if x is None or x.empty: return pd.DataFrame()
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = x.columns.get_level_values(0)
    x = x.copy()
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c in x: x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["Open", "High", "Low", "Close"])
    if x.index.tz is None: x.index = x.index.tz_localize("UTC")
    return x

def getdata(symbol, tf, period="30d"):
    for i in range(3):
        try:
            x = clean(yf.download(symbol, period=period, interval=tf, progress=False, auto_adjust=False, threads=False))
            if len(x) > 30:
                return x.iloc[:-1]
        except Exception as e:
            print("[DATA ERROR]", symbol, tf, e)
        time.sleep(1)
    return pd.DataFrame()

def addind(x):
    x = x.copy()
    x["ema20"] = x.Close.ewm(span=20, adjust=False).mean()
    x["ema50"] = x.Close.ewm(span=50, adjust=False).mean()

    d = x.Close.diff()
    g = d.clip(lower=0).rolling(14).mean()
    l = (-d.clip(upper=0)).rolling(14).mean()
    rs = g / l.replace(0, np.nan)
    x["rsi"] = 100 - 100 / (1 + rs)

    tr = pd.concat([
        x.High - x.Low,
        (x.High - x.Close.shift()).abs(),
        (x.Low - x.Close.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14).mean().fillna(x.Close * 0.01)
    return x.fillna(0)

def main():
    print("====================================")
    print(f" BTCC FUTURES SIGNAL BOT V{V}")
    print("====================================")

    state = get_state()
    positions = state.get("positions", [])

    print(f"[STATUS] Currently active positions: {len(positions)} / {MAX_SLOTS}")

    updated_positions = []
    for pos in positions:
        sym = pos["symbol"]
        x15 = addind(getdata(sym, "15m", "5d"))
        if x15.empty:
            updated_positions.append(pos)
            continue
        
        current_price = float(x15.Close.iloc[-1])
        d = pos["direction"]
        sl = pos["sl"]
        t1, t2, t3 = pos["tp1"], pos["tp2"], pos["tp3"]
        hit = pos.setdefault("hit", [])

        if d == "LONG":
            if current_price <= sl:
                tg(f"🛡 <b>BTCC 선물 · 손절가 도달</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n종목: <b>{sym}</b> (LONG)\n청산가: <code>{m(current_price)}</code>")
                continue 
            if current_price >= t3:
                if "TP1" not in hit: hit.append("TP1")
                if "TP2" not in hit: hit.append("TP2")
                tg(f"🏆 <b>BTCC 선물 · 3차 목표가 도달 (완료)</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n종목: <b>{sym}</b> (LONG)\n최종 청산가: <code>{m(current_price)}</code>")
                continue
            if current_price >= t2 and "TP2" not in hit:
                if "TP1" not in hit: hit.append("TP1")
                hit.append("TP2")
                pos["sl"] = t1
                tg(f"🎯 <b>BTCC 선물 · 2차 목표가 도달</b>\n종목: <b>{sym}</b> (LONG)\n손절가 TP1 상향")
            elif current_price >= t1 and "TP1" not in hit:
                hit.append("TP1")
                pos["sl"] = pos["entry"]
                tg(f"🎯 <b>BTCC 선물 · 1차 목표가 도달</b>\n종목: <b>{sym}</b> (LONG)\n본전 스탑 상향")
        else:
            if current_price >= sl:
                tg(f"🛡 <b>BTCC 선물 · 손절가 도달</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n종목: <b>{sym}</b> (SHORT)\n청산가: <code>{m(current_price)}</code>")
                continue
            if current_price <= t3:
                if "TP1" not in hit: hit.append("TP1")
                if "TP2" not in hit: hit.append("TP2")
                tg(f"🏆 <b>BTCC 선물 · 3차 목표가 도달 (완료)</b>\n━━━━━━━━━━━━━━━━━━━━━━━\n종목: <b>{sym}</b> (SHORT)\n최종 청산가: <code>{m(current_price)}</code>")
                continue
            if current_price <= t2 and "TP2" not in hit:
                if "TP1" not in hit: hit.append("TP1")
                hit.append("TP2")
                pos["sl"] = t1
                tg(f"🎯 <b>BTCC 선물 · 2차 목표가 도달</b>\n종목: <b>{sym}</b> (SHORT)\n손절가 TP1 상향")
            elif current_price <= t1 and "TP1" not in hit:
                hit.append("TP1")
                pos["sl"] = pos["entry"]
                tg(f"🎯 <b>BTCC 선물 · 1차 목표가 도달</b>\n종목: <b>{sym}</b> (SHORT)\n본전 스탑 상향")

        updated_positions.append(pos)

    active_symbols = [p["symbol"] for p in updated_positions]
    while len(updated_positions) < MAX_SLOTS:
        scanned_new = False
        for sym in SYMBOLS:
            if sym in active_symbols: continue
            
            x15 = addind(getdata(sym, "15m", "30d"))
            if x15.empty: continue
            
            r = x15.iloc[-1]
            e = float(r.Close)
            atr = float(r.atr) if r.atr > 0 else e * 0.015
            
            d = "LONG" if r.Close > r.ema20 else "SHORT"
            sl = e - (atr * 1.5) if d == "LONG" else e + (atr * 1.5)
            risk = abs(e - sl)
            
            t1 = e + (risk * 1.5) if d == "LONG" else e - (risk * 1.5)
            t2 = e + (risk * 2.5) if d == "LONG" else e - (risk * 2.5)
            t3 = e + (risk * 4.0) if d == "LONG" else e - (risk * 4.0)
            
            new_pos = {
                "symbol": sym, "direction": d, "entry": e,
                "sl": sl, "tp1": t1, "tp2": t2, "tp3": t3,
                "hit": [], "signal_time": ts()
            }
            updated_positions.append(new_pos)
            active_symbols.append(sym)
            
            icon = "🟢 롱 (LONG)" if d == "LONG" else "🔴 숏 (SHORT)"
            tg(f"""🚨 <b>BTCC 프로페셔널 트레이딩 시그널</b> 🚨
━━━━━━━━━━━━━━━━━━━━━━━
📌 <b>슬롯 번호: [ {len(updated_positions)} / {MAX_SLOTS} ]</b>
🪙 <b>종목명:</b> <code>#{sym}</code>
📊 <b>포지션:</b> <b>{icon}</b>
💰 <b>Entry:</b> <code>{m(e)}</code>
🛡 <b>SL:</b> <code>{m(sl)}</code>
🎯 <b>TP1:</b> <code>{m(t1)}</code>
🎯 <b>TP2:</b> <code>{m(t2)}</code>
🎯 <b>TP3:</b> <code>{m(t3)}</code>
━━━━━━━━━━━━━━━━━━━━━━━""")
            scanned_new = True
            break
        if not scanned_new: break

    state["positions"] = updated_positions
    save(STATE, state)
    print("[DONE] State successfully saved to bot_state.json")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[FATAL]", repr(e))
        raise
