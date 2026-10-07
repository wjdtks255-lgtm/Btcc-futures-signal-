import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=78
A_SCORE=85
AP_SCORE=92
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

def tg(msg,label="MESSAGE"):
    if not TOKEN or not CHAT_ID:
        print("TG CONFIG ERROR")
        return False

    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload={
        "chat_id":CHAT_ID,
        "text":msg,
        "disable_web_page_preview":True,
        "disable_notification":False
    }

    for attempt in range(2):
        try:
            print(f"TG SEND: {label} attempt={attempt+1}")
            r=requests.post(url,json=payload,timeout=20)

            try:
                data=r.json()
            except:
                data={}

            print(
                "TG RESULT:",
                f"http={r.status_code}",
                f"ok={data.get('ok')}",
                f"message_id={data.get('result',{}).get('message_id')}",
                f"description={data.get('description','')}"
            )

            if r.status_code==200 and data.get("ok") is True:
                return True

        except Exception as e:
            print("TG ERROR:",e)

        if attempt==0:
            time.sleep(1)

    return False

def get_rows():
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
        stats["data"]+=1
        return None

    rng=max(h-l,p*.0001)
    body=abs(p-o)
    body_ratio=body/rng
    upper=(h-max(o,p))/rng
    lower=(min(o,p)-l)/rng

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
        stats["trend"]+=1
        return None

    # TREND 25
    trend=10
    if direction=="LONG":
        if ph>e20h:trend+=4
        if p>e20:trend+=4
        if e20>e50>e100:trend+=7
    else:
        if ph<e20h:trend+=4
        if p<e20:trend+=4
        if e20<e50<e100:trend+=7

    # LOCATION 20
    if direction=="LONG":
        if -.45<=d20<=.35:location=18
        elif -.75<=d20<=.70:location=14
        elif -1.10<=d20<=1.10:location=8
        else:
            stats["location"]+=1
            return None
    else:
        if -.35<=d20<=.45:location=18
        elif -.70<=d20<=.75:location=14
        elif -1.10<=d20<=1.10:location=8
        else:
            stats["location"]+=1
            return None

    # TIMING 25
    timing=0
    timing_reasons=[]

    if direction=="LONG":
        if p>o:
            timing+=7
            timing_reasons.append("현재봉 상승")
        if lower>=.12:
            timing+=5
            timing_reasons.append("하단 매수 반응")
        if body_ratio>=.30:timing+=4
        if p>=e20 and lower>=.15:timing+=4
        if ch15>=0:timing+=3
        if ch15<-.50:timing-=3
    else:
        if p<o:
            timing+=7
            timing_reasons.append("현재봉 하락")
        if upper>=.12:
            timing+=5
            timing_reasons.append("상단 매도 반응")
        if body_ratio>=.30:timing+=4
        if p<=e20 and upper>=.15:timing+=4
        if ch15<=0:timing+=3
        if ch15<-.60:timing-=3

    timing=max(0,min(25,timing))

    if timing<13:
        stats["timing"]+=1
        return None

    # RSI 10
    rscore=0

    if direction=="LONG":
        if 42<=rsi<=60:rscore+=5
        elif 37<=rsi<42 or 60<rsi<=66:rscore+=3
        elif 32<=rsi<37 or 66<rsi<=70:rscore+=1

        if 40<=rsih<=62:rscore+=5
        elif 35<=rsih<40 or 62<rsih<=67:rscore+=3
        elif 32<=rsih<35 or 67<rsih<=70:rscore+=1
    else:
        if 38<=rsi<=56:rscore+=5
        elif 34<=rsi<38 or 56<rsi<=62:rscore+=3
        elif 29<=rsi<34 or 62<rsi<=68:rscore+=1

        if 36<=rsih<=58:rscore+=5
        elif 33<=rsih<36 or 58<rsih<=64:rscore+=3
        elif 30<=rsih<33 or 64<rsih<=68:rscore+=1

    # ADX 10
    adx_score=0

    if adx>=35:adx_score+=5
    elif adx>=29:adx_score+=4
    elif adx>=24:adx_score+=3
    elif adx>=18:adx_score+=2

    if adxh>=32:adx_score+=5
    elif adxh>=26:adx_score+=4
    elif adxh>=21:adx_score+=3
    elif adxh>=16:adx_score+=1

    if adx<18 or adxh<16:
        stats["adx"]+=1
        return None

    # MOMENTUM 10
    momentum=0

    if direction=="LONG":
        if 0<=ch15<=.50:momentum+=5
        elif -.20<=ch15<0:momentum+=3
        elif ch15<-.50:momentum+=1

        if 0<=ch60<=.90:momentum+=5
        elif -.30<=ch60<0:momentum+=3
        elif ch60<-.80:momentum+=1
    else:
        if -.50<=ch15<=0:momentum+=5
        elif 0<ch15<=.20:momentum+=3
        elif ch15<-.50:momentum+=2

        if -.90<=ch60<=0:momentum+=5
        elif 0<ch60<=.30:momentum+=3
        elif ch60<-.90:momentum+=2

    # VOLATILITY 5
    if .20<=atr_pct<=1.50:volatility=5
    elif .15<=atr_pct<=2.20:volatility=3
    elif atr_pct<=3:volatility=1
    else:
        stats["volatility"]+=1
        return None

    raw=trend+location+timing+rscore+adx_score+momentum+volatility

    # ANTI-CHASE
    penalty=0
    warnings=[]

    if direction=="SHORT":
        if rsih<35:
            penalty+=5
            warnings.append("1H RSI 낮음")
        if rsi<34:
            penalty+=4
            warnings.append("15M RSI 낮음")
        if ch15<-.60:
            penalty+=6
            warnings.append("15M 급락 추격 위험")
        if d20<-.70:
            penalty+=5
            warnings.append("EMA20 이격 확대")
        if ch60<-1.20:
            penalty+=4
            warnings.append("1H 급락 진행")
    else:
        if rsih>65:
            penalty+=5
            warnings.append("1H RSI 높음")
        if rsi>67:
            penalty+=4
            warnings.append("15M RSI 높음")
        if ch15>.60:
            penalty+=6
            warnings.append("15M 급등 추격 위험")
        if d20>.70:
            penalty+=5
            warnings.append("EMA20 이격 확대")
        if ch60>1.20:
            penalty+=4
            warnings.append("1H 급등 진행")

    score=max(0,min(100,int(raw-penalty)))

    # 100점 방지: 실제 진입 품질이 완벽하지 않으면 상한 적용
    if timing<21:score=min(score,94)
    if location<18:score=min(score,92)
    if rscore<8:score=min(score,90)
    if momentum<8:score=min(score,91)
    if penalty>=5:score=min(score,89)

    # 강한 추세라도 극단 추격이면 A+ 금지
    chase=False

    if direction=="SHORT":
        if rsih<33 and ch15<-.20:chase=True
        if d20<-.85:chase=True
        if ch15<-.80:chase=True
    else:
        if rsih>67 and ch15>.20:chase=True
        if d20>.85:chase=True
        if ch15>.80:chase=True

    if chase:
        score=min(score,84)
        stats["chase"]+=1

    if score<MIN_SCORE:
        stats["score"]+=1
        return None

    if score>=AP_SCORE and timing>=20 and location>=16 and penalty<=4 and not chase:
        quality="A+"
    elif score>=A_SCORE and timing>=16 and location>=13:
        quality="A"
    else:
        stats["b_grade"]+=1
        return None

    risk=max(atr*1.15,p*.005)
    risk_pct=risk/p*100

    if risk_pct>3:
        stats["risk"]+=1
        return None

    if direction=="LONG":
        sl=p-risk
        tp1=p+risk*1.5
        tp2=p+risk*2.5
        setup="EMA20 눌림 후 반등" if d20<=.35 else "상승 추세 재개"
    else:
        sl=p+risk
        tp1=p-risk*1.5
        tp2=p-risk*2.5
        setup="EMA20 반등 후 재하락" if d20>=-.35 else "하락 추세 재개"

    if atr_pct>=2:lev=3
    elif atr_pct>=1.4:lev=5
    elif atr_pct>=.8:lev=7
    else:lev=8

    reasons=[]
    reasons.append("1H EMA 상승 배열" if direction=="LONG" else "1H EMA 하락 배열")

    if location>=16:
        reasons.append("EMA20 핵심 진입 구간")

    reasons.extend(timing_reasons)

    if adx>=29 and adxh>=26:
        reasons.append("상·하위 추세 강도 확인")
    elif adx>=24:
        reasons.append("15M 추세 강도 확인")

    if 8<=rscore:
        reasons.append("RSI 진입 상태 양호")
    elif rscore>=5:
        reasons.append("RSI 중립권 접근")

    return {
        "symbol":sym(r),
        "direction":direction,
        "score":score,
        "quality":quality,
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
        "trend":trend,
        "location":location,
        "timing":timing,
        "rscore":rscore,
        "adx_score":adx_score,
        "momentum":momentum,
        "volatility":volatility,
        "penalty":penalty,
        "warnings":warnings,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 A+ HIGH QUALITY ENTRY" if s["quality"]=="A+" else "⚡ A QUALITY ENTRY"

    rr=[]
    seen=set()
    for x in s["reasons"]:
        if x not in seen:
            rr.append(x)
            seen.add(x)

    warning=""
    if s["warnings"]:
        warning="\n\n⚠️ ENTRY RISK\n"+"\n".join(
            f"• {x}" for x in s["warnings"][:3]
        )

    return (
        f"{icon} {title}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{s['symbol']}\n"
        f"📌 {'LONG 🟢' if s['direction']=='LONG' else 'SHORT 🔴'}\n"
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
        f"├ RSI 1H : {s['rsih']:.1f}\n"
        f"├ ADX 15M : {s['adx']:.1f}\n"
        f"├ ADX 1H : {s['adxh']:.1f}\n"
        f"├ 15M : {s['ch15']:+.2f}%\n"
        f"├ 1H : {s['ch60']:+.2f}%\n"
        f"└ ATR : {s['atr_pct']:.2f}%\n\n"
        "🎯 QUALITY BREAKDOWN\n"
        f"├ Trend : {s['trend']}/25\n"
        f"├ Location : {s['location']}/20\n"
        f"├ Timing : {s['timing']}/25\n"
        f"├ RSI : {s['rscore']}/10\n"
        f"├ ADX : {s['adx_score']}/10\n"
        f"├ Momentum : {s['momentum']}/10\n"
        f"└ Volatility : {s['volatility']}/5\n"
        f"Penalty : -{s['penalty']}\n\n"
        "🧠 ENTRY REASONS\n"
        +"\n".join(rr[:6])
        +warning+
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
                tg(position_msg(p,"TP2"),f"{p['symbol']} TP2")
                remove.append(key)
                continue

            if price<=p["sl"]:
                tg(position_msg(p,"SL"),f"{p['symbol']} SL")
                remove.append(key)
                continue

            if not p["tp1_hit"] and price>=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"),f"{p['symbol']} TP1")

        else:
            if price<=p["tp2"]:
                tg(position_msg(p,"TP2"),f"{p['symbol']} TP2")
                remove.append(key)
                continue

            if price>=p["sl"]:
                tg(position_msg(p,"SL"),f"{p['symbol']} SL")
                remove.append(key)
                continue

            if not p["tp1_hit"] and price<=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"),f"{p['symbol']} TP1")

    for x in remove:
        state["positions"].pop(x,None)

def main():
    print("===================================")
    print(" BTCC REAL FUTURES A+/A ENTRY BOT")
    print("===================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=get_rows()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg(
            "⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패",
            "DATA ERROR"
        )
        return

    state=load()
    before=len(state["positions"])
    check_positions(state,rs)
    after=len(state["positions"])

    if before!=after:
        print("ACTIVE CHANGE:",before,"->",after)

    stats={
        "data":0,
        "trend":0,
        "location":0,
        "timing":0,
        "adx":0,
        "volatility":0,
        "score":0,
        "risk":0,
        "chase":0,
        "b_grade":0
    }

    trend_count=0
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
                trend_count+=1

            s=analyze(r,stats)
            if s:candidates.append(s)

        except Exception as e:
            stats["data"]+=1
            print("ANALYZE ERROR:",e)

    candidates.sort(
        key=lambda x:(
            1 if x["quality"]=="A+" else 0,
            x["score"],
            x["timing"],
            x["location"],
            x["adx"]
        ),
        reverse=True
    )

    print("TREND CANDIDATES:",trend_count)
    print("A+/A QUALIFIED:",len(candidates))
    print("FILTER STATS:",stats)

    print("TOP CANDIDATES:")
    for i,s in enumerate(candidates[:10],1):
        print(
            f"#{i} {s['symbol']} {s['direction']} "
            f"{s['quality']} SCORE={s['score']} "
            f"T={s['trend']} L={s['location']} "
            f"TIME={s['timing']} "
            f"RSI1H={s['rsih']:.1f} "
            f"PENALTY={s['penalty']}"
        )

    sent=0
    ts=time.time()

    for s in candidates:
        if sent>=MAX_ALERTS:
            break

        key=s["symbol"]

        if key in state["positions"]:
            print("SKIP ACTIVE:",key)
            continue

        sid=f"{key}:{s['direction']}"
        last=float(state["signals"].get(sid,0) or 0)

        if ts-last<COOLDOWN*60:
            print("SKIP COOLDOWN:",key)
            continue

        msg=signal_msg(s)

        if not tg(msg,f"{key} {s['direction']} {s['quality']}"):
            print("SEND FAILED:",key)
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
            "quality":s["quality"],
            "entry_time":now().isoformat()
        }

        save(state)
        sent+=1

        print(
            "SIGNAL SENT:",
            key,
            s["direction"],
            s["quality"],
            s["score"]
        )

        time.sleep(.7)

    save(state)

    print("FINAL SIGNALS:",sent)
    print("ACTIVE:",len(state["positions"]))
    print("DONE")

if __name__=="__main__":
    main()
