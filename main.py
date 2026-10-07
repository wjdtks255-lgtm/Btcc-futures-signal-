import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()

STATE_FILE="bot_state.json"
TV_URL="https://scanner.tradingview.com/crypto/scan"

THRESHOLD=68
STRONG=80
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

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"positions":{},"signals":{}}
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            s=json.load(f)
        s.setdefault("positions",{})
        s.setdefault("signals",{})
        return s
    except Exception:
        return {"positions":{},"signals":{}}

def save_state(state):
    tmp=STATE_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False,indent=2)
    os.replace(tmp,STATE_FILE)

def tv_scan():
    payload={
        "filter":[
            {"left":"exchange","operation":"equal","right":"BTCC"}
        ],
        "options":{"lang":"en"},
        "markets":["crypto"],
        "symbols":{"query":{"types":["crypto"]},"tickers":[]},
        "columns":COLUMNS,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,1000]
    }

    r=requests.post(
        TV_URL,
        json=payload,
        headers={
            "User-Agent":"Mozilla/5.0",
            "Content-Type":"application/json",
            "Referer":"https://www.tradingview.com/"
        },
        timeout=30
    )
    print("TradingView:",r.status_code)
    r.raise_for_status()

    data=r.json()
    rows=data.get("data",[])
    print("TradingView BTCC rows:",len(rows))
    return rows

def val(row,i,default=0):
    try:
        x=row.get("d",[])[i]
        return float(x) if x is not None else default
    except:
        return default

def symbol_name(row):
    s=str(row.get("s",""))
    if ":" in s:
        s=s.split(":",1)[1]
    return s.replace(".P","")

def analyze(row):
    p15=val(row,0)
    v15=val(row,1)
    e20_15=val(row,2)
    e50_15=val(row,3)
    e100_15=val(row,4)
    rsi15=val(row,5)
    adx15=val(row,6)
    atr15=val(row,7)

    p60=val(row,8)
    v60=val(row,9)
    e20_60=val(row,10)
    e50_60=val(row,11)
    e100_60=val(row,12)
    rsi60=val(row,13)
    adx60=val(row,14)
    atr60=val(row,15)

    ch15=val(row,16)
    ch60=val(row,17)

    long_score=0
    short_score=0
    long_reasons=[]
    short_reasons=[]

    if e20_60>e50_60:
        long_score+=18
        long_reasons.append("1H EMA20 > EMA50")
    elif e20_60<e50_60:
        short_score+=18
        short_reasons.append("1H EMA20 < EMA50")

    if p60>e100_60:
        long_score+=10
        long_reasons.append("1H 가격 EMA100 상회")
    elif p60<e100_60:
        short_score+=10
        short_reasons.append("1H 가격 EMA100 하회")

    if p15>e20_15 and p15>e50_15:
        long_score+=18
        long_reasons.append("15M EMA20/50 위")
    elif p15<e20_15 and p15<e50_15:
        short_score+=18
        short_reasons.append("15M EMA20/50 아래")

    if p15>e100_15:
        long_score+=7
        long_reasons.append("15M EMA100 위")
    elif p15<e100_15:
        short_score+=7
        short_reasons.append("15M EMA100 아래")

    if 52<=rsi15<=72:
        long_score+=10
        long_reasons.append(f"RSI {rsi15:.1f} 상승구간")
    elif 28<=rsi15<=48:
        short_score+=10
        short_reasons.append(f"RSI {rsi15:.1f} 하락구간")

    if rsi60>=50:
        long_score+=5
        long_reasons.append(f"1H RSI {rsi60:.1f}")
    elif rsi60<50:
        short_score+=5
        short_reasons.append(f"1H RSI {rsi60:.1f}")

    if adx15>=18:
        if long_score>=short_score:
            long_score+=7
            long_reasons.append(f"ADX {adx15:.1f} 추세 확인")
        else:
            short_score+=7
            short_reasons.append(f"ADX {adx15:.1f} 추세 확인")

    if adx60>=18:
        if e20_60>e50_60:
            long_score+=5
            long_reasons.append(f"1H ADX {adx60:.1f}")
        elif e20_60<e50_60:
            short_score+=5
            short_reasons.append(f"1H ADX {adx60:.1f}")

    if ch15>0.35:
        long_score+=8
        long_reasons.append(f"15M +{ch15:.2f}%")
    elif ch15<-0.35:
        short_score+=8
        short_reasons.append(f"15M {ch15:.2f}%")

    if ch60>0.5:
        long_score+=5
        long_reasons.append(f"1H +{ch60:.2f}%")
    elif ch60<-0.5:
        short_score+=5
        short_reasons.append(f"1H {ch60:.2f}%")

    if v15>100000:
        if long_score>short_score:
            long_score+=7
            long_reasons.append("15M 거래량 증가")
        elif short_score>long_score:
            short_score+=7
            short_reasons.append("15M 거래량 증가")

    if long_score>=short_score:
        direction="LONG"
        score=long_score
        reasons=long_reasons
    else:
        direction="SHORT"
        score=short_score
        reasons=short_reasons

    if score<THRESHOLD or p15<=0 or atr15<=0:
        return None

    risk=max(atr15*1.25,p15*0.008)

    if direction=="LONG":
        sl=p15-risk
        tp1=p15+risk*1.5
        tp2=p15+risk*2.5
    else:
        sl=p15+risk
        tp1=p15-risk*1.5
        tp2=p15-risk*2.5

    atr_pct=(atr15/p15)*100 if p15 else 99

    if atr_pct>=3:
        lev=3
    elif atr_pct>=2:
        lev=5
    elif atr_pct>=1:
        lev=8
    else:
        lev=10

    return {
        "symbol":symbol_name(row),
        "direction":direction,
        "score":score,
        "price":p15,
        "sl":sl,
        "tp1":tp1,
        "tp2":tp2,
        "atr":atr15,
        "atr_pct":atr_pct,
        "leverage":lev,
        "reasons":reasons[:5],
        "time":now().isoformat()
    }

def telegram(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return False

    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    try:
        r=requests.post(
            url,
            json={
                "chat_id":CHAT_ID,
                "text":text,
                "disable_web_page_preview":True
            },
            timeout=20
        )

        if r.status_code!=200:
            print("Telegram:",r.status_code,r.text[:500])
            return False

        print("Telegram: 200")
        return True
    except Exception as e:
        print("Telegram ERROR:",e)
        return False

def telegram_check():
    if not TOKEN or not CHAT_ID:
        print("ERROR: Telegram secrets missing")
        return False

    try:
        r=requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getChat",
            params={"chat_id":CHAT_ID},
            timeout=15
        )
        print("Telegram chat check:",r.status_code)

        if r.status_code!=200:
            print("Telegram chat error:",r.text[:500])
            return False

        return True
    except Exception as e:
        print("Telegram check error:",e)
        return False

def price(x):
    if x>=1000:
        return f"{x:,.2f}"
    if x>=1:
        return f"{x:,.4f}"
    return f"{x:.8f}"

def new_signal_message(signals):
    lines=[
        "🚨 BTCC FUTURES SIGNAL",
        "━━━━━━━━━━━━━━━━━━",
        "📡 DATA : BTCC / TradingView",
        f"🕒 KST : {now().strftime('%Y-%m-%d %H:%M')}",
        ""
    ]

    for i,s in enumerate(signals,1):
        icon="🟢" if s["direction"]=="LONG" else "🔴"
        reason=" · ".join(s["reasons"])

        lines += [
            f"{icon} #{i} {s['symbol']}  {s['direction']}",
            f"⭐ SCORE : {s['score']}/100",
            f"💰 ENTRY : {price(s['price'])}",
            f"🛑 SL : {price(s['sl'])}",
            f"🎯 TP1 : {price(s['tp1'])}",
            f"🎯 TP2 : {price(s['tp2'])}",
            f"⚡ LEVERAGE : {s['leverage']}x",
            f"📊 ATR : {s['atr_pct']:.2f}%",
            f"🧠 REASON : {reason}",
            "━━━━━━━━━━━━━━━━━━"
        ]

    lines.append("⚠️ 신호는 기술적 조건 기반이며 실제 주문은 실행하지 않습니다.")
    return "\n".join(lines)

def check_positions(state,rows):
    if not state["positions"]:
        return

    latest={}
    for row in rows:
        latest[symbol_name(row)]=val(row,0)

    finished=[]

    for symbol,pos in list(state["positions"].items()):
        p=latest.get(symbol)
        if not p:
            continue

        direction=pos["direction"]
        entry=pos["entry"]
        sl=pos["sl"]
        tp1=pos["tp1"]
        tp2=pos["tp2"]

        if direction=="LONG":
            if p>=tp2:
                telegram(
                    f"🎯 BTCC TP2 HIT\n\n"
                    f"#{symbol} LONG\n"
                    f"Entry : {price(entry)}\n"
                    f"TP2 : {price(tp2)}\n"
                    f"Current : {price(p)}"
                )
                finished.append(symbol)
                continue

            if p<=sl:
                telegram(
                    f"🛑 BTCC STOP LOSS\n\n"
                    f"#{symbol} LONG\n"
                    f"Entry : {price(entry)}\n"
                    f"SL : {price(sl)}\n"
                    f"Current : {price(p)}"
                )
                finished.append(symbol)
                continue

            if not pos.get("tp1_hit") and p>=tp1:
                pos["tp1_hit"]=True
                pos["sl"]=entry
                telegram(
                    f"🎯 BTCC TP1 HIT\n\n"
                    f"#{symbol} LONG\n"
                    f"Entry : {price(entry)}\n"
                    f"TP1 : {price(tp1)}\n"
                    f"Current : {price(p)}\n\n"
                    f"🔒 SL → ENTRY"
                )

        else:
            if p<=tp2:
                telegram(
                    f"🎯 BTCC TP2 HIT\n\n"
                    f"#{symbol} SHORT\n"
                    f"Entry : {price(entry)}\n"
                    f"TP2 : {price(tp2)}\n"
                    f"Current : {price(p)}"
                )
                finished.append(symbol)
                continue

            if p>=sl:
                telegram(
                    f"🛑 BTCC STOP LOSS\n\n"
                    f"#{symbol} SHORT\n"
                    f"Entry : {price(entry)}\n"
                    f"SL : {price(sl)}\n"
                    f"Current : {price(p)}"
                )
                finished.append(symbol)
                continue

            if not pos.get("tp1_hit") and p<=tp1:
                pos["tp1_hit"]=True
                pos["sl"]=entry
                telegram(
                    f"🎯 BTCC TP1 HIT\n\n"
                    f"#{symbol} SHORT\n"
                    f"Entry : {price(entry)}\n"
                    f"TP1 : {price(tp1)}\n"
                    f"Current : {price(p)}\n\n"
                    f"🔒 SL → ENTRY"
                )

    for symbol in finished:
        state["positions"].pop(symbol,None)

def add_signals(state,signals):
    t=time.time()
    new=[]

    for s in signals:
        key=f"{s['symbol']}:{s['direction']}"
        old=state["signals"].get(key,0)

        if t-old<COOLDOWN*60:
            continue

        state["signals"][key]=t
        new.append(s)

        state["positions"][s["symbol"]]={
            "direction":s["direction"],
            "entry":s["price"],
            "sl":s["sl"],
            "tp1":s["tp1"],
            "tp2":s["tp2"],
            "tp1_hit":False,
            "created":s["time"]
        }

    return new

def main():
    print("="*55)
    print("🚀 BTCC FUTURES QUANT SCANNER V10.0")
    print("DATA: BTCC / TradingView")
    print("="*55)

    if not telegram_check():
        print("Telegram 연결 실패")
        return

    state=load_state()

    rows=tv_scan()
    print("BTCC symbols:",len(rows))

    results=[]

    for row in rows:
        try:
            s=analyze(row)
            if s:
                results.append(s)
                print(
                    f"{s['symbol']:<18} "
                    f"{s['direction']:<5} "
                    f"score={s['score']:>3}"
                )
        except Exception as e:
            print("Analyze error:",e)

    results.sort(key=lambda x:x["score"],reverse=True)

    check_positions(state,rows)

    new=add_signals(state,results[:MAX_ALERTS])

    if new:
        print("NEW SIGNALS:",len(new))
        telegram(new_signal_message(new))
    else:
        print("No new BTCC signals")

    save_state(state)

    print("="*55)
    print("ACTIVE POSITIONS:",len(state["positions"]))
    print("TOTAL SIGNAL HISTORY:",len(state["signals"]))
    print("="*55)

if __name__=="__main__":
    main()
