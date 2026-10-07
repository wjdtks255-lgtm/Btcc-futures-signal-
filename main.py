import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=78
STRONG_SCORE=90
MAX_ALERTS=3
COOLDOWN=180

COL=[
"open|15","high|15","low|15","close|15","volume|15",
"EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"open|60","high|60","low|60","close|60","volume|60",
"EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60",
"change|15","change|60"
]

HEAD={
    "User-Agent":"Mozilla/5.0",
    "Origin":"https://www.tradingview.com",
    "Referer":"https://www.tradingview.com/",
    "Content-Type":"application/json"
}

def now():
    return datetime.now(KST)

def load():
    try:
        with open(STATE_FILE,encoding="utf-8") as f:s=json.load(f)
    except:s={"positions":{},"signals":{}}
    s.setdefault("positions",{})
    s.setdefault("signals",{})
    return s

def save(s):
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:
        json.dump(s,f,ensure_ascii=False,indent=2)
    os.replace(STATE_FILE+".tmp",STATE_FILE)

def tg(msg):
    if not TOKEN or not CHAT_ID:return False
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":msg,"disable_web_page_preview":True},
            timeout=15
        )
        print("TG:",r.status_code)
        return r.ok
    except Exception as e:
        print("TG ERROR:",e)
        return False

def tv():
    payload={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[{"left":"exchange","operation":"equal","right":"BTCC"}],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    }
    try:
        r=requests.post(TV,json=payload,headers=HEAD,timeout=25)
        print("TV:",r.status_code)
        return r.json().get("data",[]) if r.status_code==200 else []
    except Exception as e:
        print("TV ERROR:",e)
        return []

def val(r,i):
    try:return float(r["d"][i])
    except:return 0.0

def sym(r):
    return str(r.get("s","")).split(":")[-1].replace(".P","")

def fmt(x):
    if x>=1000:return f"{x:,.2f}"
    if x>=1:return f"{x:.4f}"
    if x>=.01:return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def analyze(r,stats):
    o,h,l,p,v=[val(r,i) for i in range(5)]
    e20,e50,e100=[val(r,i) for i in (5,6,7)]
    rsi,adx,atr=[val(r,i) for i in (8,9,10)]

    oh,hh,lh,ph,vh=[val(r,i) for i in range(11,16)]
    e20h,e50h,e100h=[val(r,i) for i in (16,17,18)]
    rsih,adxh=[val(r,i) for i in (19,20)]
    ch15,ch60=[val(r,i) for i in (21,22)]

    if min(p,e20,e50,e100,ph,e20h,e50h,e100h,atr)<=0:
        stats["bad_data"]+=1
        return None

    rng=max(h-l,p*.0001)
    body=abs(p-o)
    upper=(h-max(o,p))/rng
    lower=(min(o,p)-l)/rng
    body_ratio=body/rng
    atr_pct=atr/p*100
    d20=(p-e20)/e20*100
    d50=(p-e50)/e50*100

    bull_h=e20h>e50h>e100h and ph>e20h
    bear_h=e20h<e50h<e100h and ph<e20h
    bull15=e20>e50>e100
    bear15=e20<e50<e100

    if bull_h and bull15:
        direction="LONG"
    elif bear_h and bear15:
        direction="SHORT"
    else:
        stats["trend_fail"]+=1
        return None

    score=0
    reasons=[]
    location=0
    trigger=0

    # 1. Trend 25
    score+=12
    reasons.append("1H EMA 정배열" if direction=="LONG" else "1H EMA 역배열")

    if direction=="LONG":
        if ph>e20h:score+=5
        if p>e20:score+=5
        if e20>e50>e100:score+=3
    else:
        if ph<e20h:score+=5
        if p<e20:score+=5
        if e20<e50<e100:score+=3

    # 2. Entry location 20
    if direction=="LONG":
        if -.60<=d20<=.80:
            location=20
        elif -.90<=d20<=1.20:
            location=13
        elif -.90<=d20<=1.70:
            location=7
        else:
            stats["location_fail"]+=1
            return None
    else:
        if -.80<=d20<=.60:
            location=20
        elif -1.20<=d20<=.90:
            location=13
        elif -1.70<=d20<=1.20:
            location=7
        else:
            stats["location_fail"]+=1
            return None

    score+=location

    if abs(d20)<=.80:
        reasons.append("EMA20 진입 구간")
    elif d20>0:
        reasons.append("EMA20 위 추세 진행")
    else:
        reasons.append("EMA20 아래 추세 진행")

    # 3. Current candle / trigger 20
    if direction=="LONG":
        if p>o:
            trigger+=8
            reasons.append("현재봉 상승")
        if lower>=.15:
            trigger+=6
            reasons.append("하단 매수 반응")
        if body_ratio>=.35:
            trigger+=4
        if p>=e20 or lower>=.20:
            trigger+=2
    else:
        if p<o:
            trigger+=8
            reasons.append("현재봉 하락")
        if upper>=.15:
            trigger+=6
            reasons.append("상단 매도 반응")
        if body_ratio>=.35:
            trigger+=4
        if p<=e20 or upper>=.20:
            trigger+=2

    if trigger<8:
        stats["trigger_fail"]+=1
        return None

    score+=min(trigger,20)

    # 4. RSI 10
    if direction=="LONG":
        if 40<=rsi<=62:score+=7
        elif 35<=rsi<40 or 62<rsi<=68:score+=5
        elif 30<=rsi<35 or 68<rsi<=72:score+=2
        else:score+=0

        if 38<=rsih<=65:score+=3
        elif 33<=rsih<=70:score+=1
    else:
        if 38<=rsi<=60:score+=7
        elif 33<=rsi<38 or 60<rsi<=65:score+=5
        elif 28<=rsi<33 or 65<rsi<=70:score+=2

        if 35<=rsih<=62:score+=3
        elif 30<=rsih<=68:score+=1

    # 5. ADX 10
    if adx>=30:score+=6
    elif adx>=24:score+=4
    elif adx>=18:score+=2

    if adxh>=30:score+=4
    elif adxh>=23:score+=3
    elif adxh>=18:score+=1

    if adx<16 or adxh<15:
        stats["weak_trend"]+=1
        return None

    reasons.append(f"ADX {adx:.1f}/{adxh:.1f}")

    # 6. Momentum 10
    if direction=="LONG":
        if ch15>0:score+=4
        elif ch15>-0.30:score+=2
        if ch60>0:score+=4
        elif ch60>-0.50:score+=2
        if ch15>=-0.15:score+=2
    else:
        if ch15<0:score+=4
        elif ch15<0.30:score+=2
        if ch60<0:score+=4
        elif ch60<0.50:score+=2
        if ch15<=0.15:score+=2

    # 7. Volatility 5
    if .20<=atr_pct<=1.50:score+=5
    elif .15<=atr_pct<=2.20:score+=3
    elif atr_pct<=3.0:score+=1
    else:
        stats["volatility_fail"]+=1
        return None

    # 극단적인 추격 진입 감점
    if direction=="SHORT":
        if rsi<32:score-=5
        if rsih<35:score-=4
        if d20<-.80:score-=4
    else:
        if rsi>68:score-=5
        if rsih>65:score-=4
        if d20>.80:score-=4

    score=max(0,min(100,int(score)))

    if score<MIN_SCORE:
        stats["score_fail"]+=1
        return None

    if direction=="LONG":
        setup="EMA20 눌림·반등 진입" if d20<=.30 else "상승 추세 재개"
    else:
        setup="EMA20 반등·재하락 진입" if d20>=-.30 else "하락 추세 재개"

    risk=max(atr*1.15,p*.005)
    risk_pct=risk/p*100

    if risk_pct>3.0:
        stats["risk_fail"]+=1
        return None

    if direction=="LONG":
        sl=p-risk
        tp1=p+risk*1.5
        tp2=p+risk*2.5
    else:
        sl=p+risk
        tp1=p-risk*1.5
        tp2=p-risk*2.5

    if atr_pct>=2.0:lev=3
    elif atr_pct>=1.4:lev=5
    elif atr_pct>=.8:lev=7
    else:lev=8

    strong=score>=STRONG_SCORE and adx>=27 and adxh>=22

    return {
        "symbol":sym(r),
        "direction":direction,
        "score":score,
        "strong":strong,
        "price":p,
        "sl":sl,
        "tp1":tp1,
        "tp2":tp2,
        "rsi":rsi,
        "rsih":rsih,
        "adx":adx,
        "adxh":adxh,
        "ch15":ch15,
        "ch60":ch60,
        "atr_pct":atr_pct,
        "lev":lev,
        "setup":setup,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 A+ STRONG ENTRY" if s["strong"] else "⚡ A ENTRY"

    rr=[]
    seen=set()
    for x in s["reasons"]:
        if x not in seen:
            rr.append(x)
            seen.add(x)

    return (
        f"{icon} {title}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{s['symbol']}\n"
        f"📌 {'LONG 🟢' if s['direction']=='LONG' else 'SHORT 🔴'}\n"
        f"⭐ Score : {s['score']}/100\n"
        f"🎯 Setup : {s['setup']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 TRADE PLAN\n"
        f"├ Entry : {fmt(s['price'])}\n"
        f"├ SL : {fmt(s['sl'])}\n"
        f"├ TP1 : {fmt(s['tp1'])}\n"
        f"└ TP2 : {fmt(s['tp2'])}\n\n"
        "📊 MARKET\n"
        f"├ RSI 15M : {s['rsi']:.1f}\n"
        f"├ RSI 1H : {s['rsih']:.1f}\n"
        f"├ ADX 15M : {s['adx']:.1f}\n"
        f"├ ADX 1H : {s['adxh']:.1f}\n"
        f"├ 15M : {s['ch15']:+.2f}%\n"
        f"├ 1H : {s['ch60']:+.2f}%\n"
        f"└ ATR : {s['atr_pct']:.2f}%\n\n"
        "🧠 ENTRY REASONS\n"+
        "\n".join(f"• {x}" for x in rr[:6])+
        "\n\n⚙️ RISK\n"
        f"├ Leverage : {s['lev']}x\n"
        "├ TP1 → SL = ENTRY\n"
        "└ TP2 → TRACKING END\n\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ Signal only / No auto order"
    )

def position_msg(p,kind):
    sym=p.get("symbol","UNKNOWN")
    d=p.get("direction","LONG")

    if kind=="TP1":
        return (
            "🎯 TP1 HIT\n\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
            f"💰 Entry : {fmt(p.get('entry',0))}\n"
            f"🎯 TP1 : {fmt(p.get('tp1',0))}\n\n"
            "🔒 SL → ENTRY\n"
            "원금 방어 모드로 전환합니다."
        )

    if kind=="TP2":
        return (
            "🎯 TP2 HIT\n\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
            f"🎯 TP2 : {fmt(p.get('tp2',0))}\n\n"
            "✅ 목표 구간 도달\n"
            "포지션 추적 종료."
        )

    return (
        "🛑 STOP LOSS\n\n"
        f"🪙 #{sym}\n"
        f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
        f"🛑 SL : {fmt(p.get('sl',0))}\n\n"
        "포지션 추적 종료."
    )

def check_positions(state,rs):
    by={sym(r):r for r in rs}
    remove=[]

    for key,p in list(state["positions"].items()):
        if not isinstance(p,dict):
            remove.append(key)
            continue

        p.setdefault("symbol",key)
        p.setdefault("tp1_hit",False)

        if any(k not in p for k in ("direction","entry","sl","tp1","tp2")):
            remove.append(key)
            continue

        r=by.get(p["symbol"])
        if not r:continue

        price=val(r,3)
        d=p["direction"]

        if d=="LONG":
            if price>=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(key)
                continue
            if price<=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(key)
                continue
            if not p["tp1_hit"] and price>=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
        else:
            if price<=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(key)
                continue
            if price>=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(key)
                continue
            if not p["tp1_hit"] and price<=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))

    for x in remove:
        state["positions"].pop(x,None)

def main():
    print("====================================")
    print(" BTCC REAL FUTURES SMART ENTRY BOT")
    print("====================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=tv()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg("⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패")
        return

    state=load()
    check_positions(state,rs)

    stats={
        "bad_data":0,
        "trend_fail":0,
        "location_fail":0,
        "trigger_fail":0,
        "weak_trend":0,
        "volatility_fail":0,
        "score_fail":0,
        "risk_fail":0
    }

    trend=0
    candidates=[]

    for r in rs:
        try:
            p=val(r,3)
            ph=val(r,14)
            e20=val(r,5)
            e50=val(r,6)
            e100=val(r,7)
            e20h=val(r,16)
            e50h=val(r,17)
            e100h=val(r,18)

            if (
                (e20h>e50h>e100h and ph>e20h and e20>e50>e100) or
                (e20h<e50h<e100h and ph<e20h and e20<e50<e100)
            ):
                trend+=1

            s=analyze(r,stats)
            if s:candidates.append(s)
        except Exception as e:
            stats["bad_data"]+=1
            print("ANALYZE ERROR:",e)

    candidates.sort(
        key=lambda x:(x["strong"],x["score"],x["adx"],x["adxh"]),
        reverse=True
    )

    print("TREND CANDIDATES:",trend)
    print("QUALIFIED BEFORE SCORE:",len(candidates))
    print("FILTER STATS:",stats)

    sent=0
    ts=time.time()

    for s in candidates:
        if sent>=MAX_ALERTS:break

        key=s["symbol"]
        if key in state["positions"]:continue

        sid=f"{key}:{s['direction']}"
        last=float(state["signals"].get(sid,0) or 0)

        if ts-last<COOLDOWN*60:
            continue

        if not tg(signal_msg(s)):
            continue

        state["signals"][sid]=ts
        state["positions"][key]={
            "symbol":key,
            "direction":s["direction"],
            "entry":s["price"],
            "sl":s["sl"],
            "tp1":s["tp1"],
            "tp2":s["tp2"],
            "tp1_hit":False,
            "score":s["score"],
            "entry_time":now().isoformat()
        }

        save(state)
        sent+=1
        time.sleep(.7)

    save(state)

    print("FINAL SIGNALS:",sent)
    print("ACTIVE:",len(state["positions"]))
    print("DONE")

if __name__=="__main__":
    main()
