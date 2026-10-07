import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=76
A_SCORE=84
AP_SCORE=91
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

    # -------------------------
    # 1. TREND QUALITY / 25
    # -------------------------
    trend=0

    if direction=="LONG":
        trend+=10
        if ph>e20h:trend+=5
        if p>e20:trend+=5
        if e20>e50>e100:trend+=5
    else:
        trend+=10
        if ph<e20h:trend+=5
        if p<e20:trend+=5
        if e20<e50<e100:trend+=5

    # -------------------------
    # 2. LOCATION / 20
    # -------------------------
    location=0

    if direction=="LONG":
        if -.45<=d20<=.35:
            location=20
        elif -.75<=d20<=.70:
            location=16
        elif -1.10<=d20<=1.10:
            location=9
        else:
            stats["location"]+=1
            return None
    else:
        if -.35<=d20<=.45:
            location=20
        elif -.70<=d20<=.75:
            location=16
        elif -1.10<=d20<=1.10:
            location=9
        else:
            stats["location"]+=1
            return None

    # -------------------------
    # 3. TIMING / 25
    # -------------------------
    timing=0
    timing_reasons=[]

    if direction=="LONG":
        if p>o:
            timing+=8
            timing_reasons.append("현재봉 상승")
        if lower>=.12:
            timing+=6
            timing_reasons.append("하단 매수 반응")
        if body_ratio>=.30:
            timing+=4
        if p>=e20 and lower>=.15:
            timing+=4
        if ch15>=0:
            timing+=3
    else:
        if p<o:
            timing+=8
            timing_reasons.append("현재봉 하락")
        if upper>=.12:
            timing+=6
            timing_reasons.append("상단 매도 반응")
        if body_ratio>=.30:
            timing+=4
        if p<=e20 and upper>=.15:
            timing+=4
        if ch15<=0:
            timing+=3

    if timing<14:
        stats["timing"]+=1
        return None

    # -------------------------
    # 4. RSI / 10
    # -------------------------
    rscore=0
    rsi_state="NORMAL"

    if direction=="LONG":
        if 42<=rsi<=62:rscore+=6
        elif 36<=rsi<42 or 62<rsi<=67:rscore+=4
        elif 31<=rsi<36 or 67<rsi<=71:rscore+=1

        if 40<=rsih<=64:rscore+=4
        elif 35<=rsih<40 or 64<rsih<=68:rscore+=2

        if rsi>67 or rsih>64:rsi_state="HOT"
        if rsi<36 or rsih<35:rsi_state="WEAK"
    else:
        if 38<=rsi<=57:rscore+=6
        elif 34<=rsi<38 or 57<rsi<=63:rscore+=4
        elif 29<=rsi<34 or 63<rsi<=68:rscore+=1

        if 35<=rsih<=60:rscore+=4
        elif 31<=rsih<35 or 60<rsih<=66:rscore+=2

        if rsi<34 or rsih<34:rsi_state="OVERSOLD"
        if rsi>63 or rsih>63:rsi_state="HOT"

    # -------------------------
    # 5. ADX / 10
    # -------------------------
    adx_score=0

    if adx>=35:adx_score+=6
    elif adx>=28:adx_score+=5
    elif adx>=23:adx_score+=4
    elif adx>=18:adx_score+=2

    if adxh>=32:adx_score+=4
    elif adxh>=25:adx_score+=3
    elif adxh>=20:adx_score+=2
    elif adxh>=16:adx_score+=1

    if adx<18 or adxh<16:
        stats["adx"]+=1
        return None

    # -------------------------
    # 6. MOMENTUM / 10
    # -------------------------
    momentum=0

    if direction=="LONG":
        if .00<=ch15<=.60:momentum+=5
        elif -.20<=ch15<0:momentum+=3
        elif ch15<-.50:momentum+=1

        if .00<=ch60<=1.00:momentum+=5
        elif -.30<=ch60<0:momentum+=3
        elif ch60<-.80:momentum+=1
    else:
        if -.60<=ch15<=0:momentum+=5
        elif 0<ch15<=.20:momentum+=3
        elif ch15<-.60:momentum+=2

        if -1.00<=ch60<=0:momentum+=5
        elif 0<ch60<=.30:momentum+=3
        elif ch60<-1.00:momentum+=2

    # -------------------------
    # 7. VOLATILITY / 5
    # -------------------------
    if .20<=atr_pct<=1.50:
        volatility=5
    elif .15<=atr_pct<=2.20:
        volatility=3
    elif atr_pct<=3:
        volatility=1
    else:
        stats["volatility"]+=1
        return None

    raw=trend+location+min(timing,25)+rscore+adx_score+momentum+volatility

    # -------------------------
    # ANTI-CHASE PENALTY
    # -------------------------
    penalty=0
    warnings=[]

    if direction=="SHORT":
        if rsih<35:
            penalty+=7
            warnings.append("1H RSI 과매도권")
        if rsi<34:
            penalty+=5
            warnings.append("15M RSI 과매도권")
        if ch15<-0.60:
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
            penalty+=7
            warnings.append("1H RSI 과매수권")
        if rsi>67:
            penalty+=5
            warnings.append("15M RSI 과매수권")
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

    # 극단적인 추격은 B 이하로 강등
    chase=False

    if direction=="SHORT":
        if rsih<32 and ch15<-.25:
            chase=True
        if d20<-.90:
            chase=True
    else:
        if rsih>68 and ch15>.25:
            chase=True
        if d20>.90:
            chase=True

    if chase:
        score=min(score,82)
        stats["chase"]+=1

    if score<MIN_SCORE:
        stats["score"]+=1
        return None

    # -------------------------
    # QUALITY
    # -------------------------
    if score>=AP_SCORE and timing>=20 and location>=16 and penalty<=4:
        quality="A+"
    elif score>=A_SCORE and timing>=17 and location>=13 and penalty<=8:
        quality="A"
    else:
        quality="B"

    # B는 후보로만 계산, 알림은 하지 않음
    if quality=="B":
        stats["b_grade"]+=1
        return None

    # A+ 조건 추가
    if quality=="A+":
        if direction=="SHORT" and rsih<34:
            quality="A"
        elif direction=="LONG" and rsih>66:
            quality="A"

    risk=max(atr*1.15,p*.005)
    risk_pct=risk/p*100

    if risk_pct>3.0:
        stats["risk"]+=1
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

    if direction=="LONG":
        setup="EMA20 눌림 후 반등"
        if d20>.35:setup="상승 추세 재개"
    else:
        setup="EMA20 반등 후 재하락"
        if d20<-.35:setup="하락 추세 재개"

    reasons=[]
    reasons.append("1H EMA 상승 배열" if direction=="LONG" else "1H EMA 하락 배열")

    if location>=16:
        reasons.append("EMA20 핵심 진입 구간")

    reasons.extend(timing_reasons)

    if adx>=28 and adxh>=25:
        reasons.append("상·하위 추세 강도 확인")
    elif adx>=23:
        reasons.append("15M 추세 강도 확인")

    if rsi_state=="NORMAL":
        reasons.append("RSI 과열 없는 진입")
    elif rsi_state=="OVERSOLD":
        reasons.append("강한 하락 추세지만 과매도 주의")
    elif rsi_state=="HOT":
        reasons.append("강한 상승 추세지만 과매수 주의")

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
    if s["quality"]=="A+":
        title="🔥 A+ HIGH QUALITY ENTRY"
    else:
        title="⚡ A QUALITY ENTRY"

    icon="🟢" if s["direction"]=="LONG" else "🔴"

    lines=[]
    seen=set()
    for x in s["reasons"]:
        if x not in seen:
            lines.append(f"• {x}")
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
        +"\n".join(lines[:6])+
        warning+
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
        tg("⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패")
        return

    state=load()
    check_positions(state,rs)

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

    for i,s in enumerate(candidates[:10],1):
        print(
            f"#{i} {s['symbol']} {s['direction']} "
            f"{s['quality']} SCORE={s['score']} "
            f"T={s['trend']} L={s['location']} "
            f"TIME={s['timing']} RSI1H={s['rsih']:.1f}"
        )

    sent=0
    ts=time.time()

    for s in candidates:
        if sent>=MAX_ALERTS:break

        key=s["symbol"]

        if key in state["positions"]:
            continue

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
            "quality":s["quality"],
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
