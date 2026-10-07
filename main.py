import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()

STATE_FILE="bot_state.json"
SYMBOL_FILE="btcc_symbols.json"
TV_URL="https://scanner.tradingview.com/crypto/scan"

THRESHOLD=72
STRONG=85
COOLDOWN=180
MAX_ALERTS=5
KST=timezone(timedelta(hours=9))

COLUMNS=[
"close|15","volume|15","EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"close|60","volume|60","EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60","ATR|60",
"change|15","change|60"
]

def now():
    return datetime.now(KST)

def load_json(path,default):
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path,data):
    tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(tmp,path)

def load_state():
    s=load_json(STATE_FILE,{"positions":{},"signals":{}})
    s.setdefault("positions",{})
    s.setdefault("signals",{})
    return s

def tv_request(payload):
    r=requests.post(
        TV_URL,
        json=payload,
        headers={
            "User-Agent":"Mozilla/5.0",
            "Content-Type":"application/json",
            "Origin":"https://www.tradingview.com",
            "Referer":"https://www.tradingview.com/"
        },
        timeout=30
    )
    print("TradingView:",r.status_code)
    if r.status_code!=200:
        print(r.text[:500])
        return []
    try:
        return r.json().get("data",[])
    except:
        return []

def get_btcc_rows():
    base={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "symbols":{"query":{"types":["crypto"]},"tickers":[]},
        "columns":COLUMNS,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,5000]
    }

    # 1차: BTCC exchange 직접 필터
    p=dict(base)
    p["filter"]=[{"left":"exchange","operation":"equal","right":"BTCC"}]

    for attempt in range(3):
        rows=tv_request(p)
        btcc=[x for x in rows if str(x.get("s","")).upper().startswith("BTCC:")]
        if btcc:
            print("BTCC rows:",len(btcc))
            save_json(SYMBOL_FILE,[x.get("s") for x in btcc])
            return btcc
        print("BTCC direct scan empty:",attempt+1)
        time.sleep(2)

    # 2차: exchange 필터 제거 후 BTCC: 심볼을 직접 추출
    print("BTCC direct filter failed -> broad scan")
    for attempt in range(3):
        rows=tv_request(base)
        btcc=[x for x in rows if str(x.get("s","")).upper().startswith("BTCC:")]
        if btcc:
            print("BTCC broad rows:",len(btcc))
            save_json(SYMBOL_FILE,[x.get("s") for x in btcc])
            return btcc
        print("BTCC broad scan empty:",attempt+1)
        time.sleep(2)

    # 3차: 이전 정상 BTCC 심볼 캐시가 있으면 사용
    cached=load_json(SYMBOL_FILE,[])
    if cached:
        print("Using cached BTCC symbols:",len(cached))
        return get_cached_rows(cached)

    return []

def get_cached_rows(symbols):
    p={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "symbols":{"query":{"types":["crypto"]},"tickers":symbols},
        "columns":COLUMNS,
        "range":[0,len(symbols)]
    }

    rows=tv_request(p)
    btcc=[x for x in rows if str(x.get("s","")).upper().startswith("BTCC:")]

    if btcc:
        print("Cached BTCC rows:",len(btcc))
    return btcc

def val(row,i,d=0):
    try:
        x=row.get("d",[])[i]
        return float(x) if x is not None else d
    except:
        return d

def symbol(row):
    s=str(row.get("s",""))
    s=s.split(":",1)[-1]
    return s.replace(".P","")

def analyze(row):
    p15,v15,e20,e50,e100,rsi,adx,atr=[
        val(row,i) for i in range(8)
    ]
    p60,v60,e20h,e50h,e100h,rsih,adxh,atrh=[
        val(row,i) for i in range(8,16)
    ]
    ch15,ch60=val(row,16),val(row,17)

    if p15<=0 or atr<=0:
        return None

    L=S=0
    lr=[]
    sr=[]

    if e20h>e50h:
        L+=18;lr.append("1H EMA20 > EMA50")
    elif e20h<e50h:
        S+=18;sr.append("1H EMA20 < EMA50")

    if p60>e100h:
        L+=10;lr.append("1H 가격 EMA100 상회")
    elif p60<e100h:
        S+=10;sr.append("1H 가격 EMA100 하회")

    if p15>e20 and p15>e50:
        L+=18;lr.append("15M EMA20/50 위")
    elif p15<e20 and p15<e50:
        S+=18;sr.append("15M EMA20/50 아래")

    if p15>e100:
        L+=7;lr.append("15M EMA100 위")
    elif p15<e100:
        S+=7;sr.append("15M EMA100 아래")

    if 52<=rsi<=72:
        L+=10;lr.append(f"RSI {rsi:.1f}")
    elif 28<=rsi<=48:
        S+=10;sr.append(f"RSI {rsi:.1f}")

    if rsih>=50:
        L+=5;lr.append(f"1H RSI {rsih:.1f}")
    else:
        S+=5;sr.append(f"1H RSI {rsih:.1f}")

    if adx>=18:
        if L>=S:
            L+=7;lr.append(f"ADX {adx:.1f}")
        else:
            S+=7;sr.append(f"ADX {adx:.1f}")

    if adxh>=18:
        if e20h>e50h:
            L+=5;lr.append(f"1H ADX {adxh:.1f}")
        elif e20h<e50h:
            S+=5;sr.append(f"1H ADX {adxh:.1f}")

    if ch15>0.35:
        L+=8;lr.append(f"15M +{ch15:.2f}%")
    elif ch15<-0.35:
        S+=8;sr.append(f"15M {ch15:.2f}%")

    if ch60>0.5:
        L+=5;lr.append(f"1H +{ch60:.2f}%")
    elif ch60<-0.5:
        S+=5;sr.append(f"1H {ch60:.2f}%")

    if v15>100000:
        if L>S:
            L+=7;lr.append("거래량 확인")
        elif S>L:
            S+=7;sr.append("거래량 확인")

    direction="LONG" if L>=S else "SHORT"
    score=max(L,S)

    if score<THRESHOLD:
        return None

    reasons=lr if direction=="LONG" else sr
    risk=max(atr*1.25,p15*0.008)

    if direction=="LONG":
        sl=p15-risk
        tp1=p15+risk*1.5
        tp2=p15+risk*2.5
    else:
        sl=p15+risk
        tp1=p15-risk*1.5
        tp2=p15-risk*2.5

    atr_pct=atr/p15*100

    if atr_pct>=3:
        lev=3
    elif atr_pct>=2:
        lev=5
    elif atr_pct>=1:
        lev=8
    else:
        lev=10

    return {
        "symbol":symbol(row),
        "tv_symbol":row.get("s",""),
        "direction":direction,
        "score":score,
        "price":p15,
        "sl":sl,
        "tp1":tp1,
        "tp2":tp2,
        "atr":atr,
        "atr_pct":atr_pct,
        "leverage":lev,
        "rsi":rsi,
        "adx":adx,
        "change15":ch15,
        "change60":ch60,
        "reasons":reasons[:5],
        "time":now().isoformat()
    }

def telegram(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return False

    try:
        r=requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id":CHAT_ID,
                "text":text,
                "disable_web_page_preview":True
            },
            timeout=20
        )
        if r.status_code!=200:
            print("Telegram:",r.status_code,r.text[:1000])
            return False
        print("Telegram: 200")
        return True
    except Exception as e:
        print("Telegram ERROR:",e)
        return False

def telegram_check():
    try:
        r=requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getChat",
            params={"chat_id":CHAT_ID},
            timeout=15
        )
        print("Telegram chat check:",r.status_code)
        if r.status_code!=200:
            print(r.text[:500])
            return False
        return True
    except Exception as e:
        print("Telegram check ERROR:",e)
        return False

def fmt(x):
    if x>=1000:
        return f"{x:,.2f}"
    if x>=1:
        return f"{x:.4f}"
    return f"{x:.8f}"

def signal_message(signals):
    out=[
        "🚨 BTCC FUTURES SIGNAL",
        "━━━━━━━━━━━━━━━━━━━━",
        "📡 BTCC PERPETUAL FUTURES",
        "📊 DATA : TradingView / BTCC",
        f"🕒 KST : {now().strftime('%Y-%m-%d %H:%M')}",
        ""
    ]

    for i,s in enumerate(signals,1):
        icon="🟢" if s["direction"]=="LONG" else "🔴"
        strength="🔥 STRONG" if s["score"]>=STRONG else "⚡ SIGNAL"

        out += [
            f"{icon} {strength} #{i}",
            f"#{s['symbol']}  {s['direction']}",
            f"⭐ SCORE : {s['score']}/100",
            f"💰 ENTRY : {fmt(s['price'])}",
            f"🛑 SL : {fmt(s['sl'])}",
            f"🎯 TP1 : {fmt(s['tp1'])}",
            f"🎯 TP2 : {fmt(s['tp2'])}",
            f"⚡ LEVERAGE : {s['leverage']}x",
            f"📈 RSI : {s['rsi']:.1f}",
            f"📊 ADX : {s['adx']:.1f}",
            f"📉 15M : {s['change15']:+.2f}%",
            f"📉 1H : {s['change60']:+.2f}%",
            "🧠 REASON :",
            *[f"• {x}" for x in s["reasons"]],
            f"🔗 {s['tv_symbol']}",
            "━━━━━━━━━━━━━━━━━━━━"
        ]

    out.append("⚠️ 자동 주문 없음 / BTCC 선물 분석 신호")
    return "\n".join(out)

def check_positions(state,rows):
    if not state["positions"]:
        return

    latest={symbol(r):val(r,0) for r in rows}
    closed=[]

    for sym,pos in list(state["positions"].items()):
        p=latest.get(sym)
        if not p:
            continue

        d=pos["direction"]
        entry=pos["entry"]
        sl=pos["sl"]
        tp1=pos["tp1"]
        tp2=pos["tp2"]

        if d=="LONG":
            if p>=tp2:
                telegram(
                    f"🎯 BTCC TP2 HIT\n\n#{sym} LONG\n"
                    f"Entry : {fmt(entry)}\nTP2 : {fmt(tp2)}\n"
                    f"Current : {fmt(p)}"
                )
                closed.append(sym)
                continue

            if p<=sl:
                telegram(
                    f"🛑 BTCC STOP LOSS\n\n#{sym} LONG\n"
                    f"Entry : {fmt(entry)}\nSL : {fmt(sl)}\n"
                    f"Current : {fmt(p)}"
                )
                closed.append(sym)
                continue

            if not pos.get("tp1_hit") and p>=tp1:
                pos["tp1_hit"]=True
                pos["sl"]=entry
                telegram(
                    f"🎯 BTCC TP1 HIT\n\n#{sym} LONG\n"
                    f"Entry : {fmt(entry)}\nTP1 : {fmt(tp1)}\n"
                    f"Current : {fmt(p)}\n\n🔒 SL → ENTRY"
                )

        else:
            if p<=tp2:
                telegram(
                    f"🎯 BTCC TP2 HIT\n\n#{sym} SHORT\n"
                    f"Entry : {fmt(entry)}\nTP2 : {fmt(tp2)}\n"
                    f"Current : {fmt(p)}"
                )
                closed.append(sym)
                continue

            if p>=sl:
                telegram(
                    f"🛑 BTCC STOP LOSS\n\n#{sym} SHORT\n"
                    f"Entry : {fmt(entry)}\nSL : {fmt(sl)}\n"
                    f"Current : {fmt(p)}"
                )
                closed.append(sym)
                continue

            if not pos.get("tp1_hit") and p<=tp1:
                pos["tp1_hit"]=True
                pos["sl"]=entry
                telegram(
                    f"🎯 BTCC TP1 HIT\n\n#{sym} SHORT\n"
                    f"Entry : {fmt(entry)}\nTP1 : {fmt(tp1)}\n"
                    f"Current : {fmt(p)}\n\n🔒 SL → ENTRY"
                )

    for sym in closed:
        state["positions"].pop(sym,None)

def add_new_signals(state,results):
    t=time.time()
    new=[]

    for s in results:
        key=f"{s['symbol']}:{s['direction']}"
        if t-state["signals"].get(key,0)<COOLDOWN*60:
            continue

        state["signals"][key]=t

        state["positions"][s["symbol"]]={
            "direction":s["direction"],
            "entry":s["price"],
            "sl":s["sl"],
            "tp1":s["tp1"],
            "tp2":s["tp2"],
            "tp1_hit":False,
            "created":s["time"]
        }

        new.append(s)

    return new

def main():
    print("="*55)
    print("🚀 BTCC FUTURES QUANT SCANNER V11.0")
    print("DATA: BTCC / TradingView")
    print("="*55)

    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing")

    if not telegram_check():
        return

    state=load_state()
    rows=get_btcc_rows()

    print("BTCC symbols:",len(rows))

    if not rows:
        print("ERROR: BTCC DATA UNAVAILABLE")
        telegram(
            "⚠️ BTCC DATA CONNECTION WARNING\n\n"
            "TradingView에서 BTCC 선물 데이터가 일시적으로 반환되지 않았습니다.\n"
            "신호 계산을 중단했습니다.\n\n"
            f"🕒 KST : {now().strftime('%Y-%m-%d %H:%M')}"
        )
        save_json(STATE_FILE,state)
        return

    results=[]

    for row in rows:
        try:
            s=analyze(row)
            if s:
                results.append(s)
                print(
                    f"{s['symbol']:<18}"
                    f"{s['direction']:<6}"
                    f"score={s['score']:>3}"
                )
        except Exception as e:
            print("Analyze error:",e)

    results.sort(key=lambda x:x["score"],reverse=True)

    check_positions(state,rows)

    new=add_new_signals(state,results[:MAX_ALERTS])

    if new:
        print("NEW SIGNALS:",len(new))
        telegram(signal_message(new))
    else:
        print("No new BTCC signals")

    save_json(STATE_FILE,state)

    print("="*55)
    print("BTCC ROWS:",len(rows))
    print("QUALIFIED:",len(results))
    print("NEW:",len(new))
    print("ACTIVE POSITIONS:",len(state["positions"]))
    print("SIGNAL HISTORY:",len(state["signals"]))
    print("="*55)

if __name__=="__main__":
    main()
