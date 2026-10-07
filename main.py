import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=84
STRONG_SCORE=91
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

def tv(payload):
    try:
        r=requests.post(TV,json=payload,headers=HEAD,timeout=25)
        print("TV:",r.status_code)
        return r.json().get("data",[]) if r.status_code==200 else []
    except Exception as e:
        print("TV ERROR:",e)
        return []

def rows():
    return tv({
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[{"left":"exchange","operation":"equal","right":"BTCC"}],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    })

def val(r,i):
    try:return float(r["d"][i])
    except:return 0.0

def symbol(r):
    return str(r.get("s","")).split(":")[-1].replace(".P","")

def fmt(x):
    if x>=1000:return f"{x:,.2f}"
    if x>=1:return f"{x:.4f}"
    if x>=.01:return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def analyze(r):
    o,h,l,p,v=[val(r,i) for i in range(5)]
    e20,e50,e100=[val(r,i) for i in (5,6,7)]
    rsi,adx,atr=[val(r,i) for i in (8,9,10)]

    oh,hh,lh,ph,vh=[val(r,i) for i in range(11,16)]
    e20h,e50h,e100h=[val(r,i) for i in (16,17,18)]
    rsih,adxh=[val(r,i) for i in (19,20)]
    ch15,ch60=[val(r,i) for i in (21,22)]

    if min(o,h,l,p,e20,e50,e100,ph,e20h,e50h,e100h,atr)<=0:return None

    atr_pct=atr/p*100
    d20=(p-e20)/e20*100
    d50=(p-e50)/e50*100

    rng=h-l
    if rng<=0:return None

    body=abs(p-o)
    body_ratio=body/rng
    upper=(h-max(o,p))/rng
    lower=(min(o,p)-l)/rng
    bull=p>o
    bear=p<o
    vr=v/max(vh,1)

    bull_h=e20h>e50h>e100h and ph>e20h
    bear_h=e20h<e50h<e100h and ph<e20h
    bull15=e20>e50>e100 and p>e20
    bear15=e20<e50<e100 and p<e20

    if bull_h and bull15:direction="LONG"
    elif bear_h and bear15:direction="SHORT"
    else:return None

    # 기본 품질
    if adx<24 or adxh<20:return None
    if v<100000 or vh<100000:return None
    if atr_pct<.20 or atr_pct>2.5:return None

    # 과열/과매도 추격 차단
    if direction=="LONG":
        if rsi>=67 or rsih>=68:return None
        if rsi<=31 or rsih<=34:return None
        if d20>1.10 or d50>2.8:return None
    else:
        if rsi<=33 or rsih<=32:return None
        if rsi>=69 or rsih>=68:return None
        if d20<-1.10 or d50<-2.8:return None

    score=0
    reasons=[]
    setup=""
    timing=0

    # 추세 25
    if direction=="LONG":
        score+=12
        reasons.append("1시간 EMA 상승 배열")
        if ph>e20h:
            score+=3
            reasons.append("1시간 EMA20 위")
        score+=7
        reasons.append("15분 EMA 상승 배열")
        if p>e20:score+=3
    else:
        score+=12
        reasons.append("1시간 EMA 하락 배열")
        if ph<e20h:
            score+=3
            reasons.append("1시간 EMA20 아래")
        score+=7
        reasons.append("15분 EMA 하락 배열")
        if p<e20:score+=3

    # 진입 위치 25
    if direction=="LONG":
        if -.25<=d20<=.35:
            timing=15
            score+=15
            setup="EMA20 눌림 후 재상승"
            reasons.append("EMA20 눌림 구간")
        elif .35<d20<=.70:
            timing=12
            score+=12
            setup="EMA20 추세 재개"
            reasons.append("EMA20 위 추세 재개")
        elif -.40<=d20<-.25:
            timing=10
            score+=10
            setup="EMA20 회복"
            reasons.append("EMA20 회복 구간")
        else:return None

        # 반드시 현재봉에서 매수 반전 확인
        if bull and lower>=.22 and body_ratio>=.28:
            score+=10
            reasons.append("하단 매수 반전 확인")
        elif bull and body_ratio>=.60:
            score+=7
            reasons.append("강한 상승 캔들 확인")
        else:
            return None

        if ch15>1.0:return None

    else:
        if -.35<=d20<=.25:
            timing=15
            score+=15
            setup="EMA20 반등 후 재하락"
            reasons.append("EMA20 반등 실패 구간")
        elif -.70<=d20<-.35:
            timing=12
            score+=12
            setup="EMA20 추세 재개"
            reasons.append("EMA20 아래 추세 재개")
        elif .25<d20<=.40:
            timing=10
            score+=10
            setup="EMA20 이탈"
            reasons.append("EMA20 하향 이탈 구간")
        else:return None

        # 반드시 현재봉에서 매도 반전 확인
        if bear and upper>=.22 and body_ratio>=.28:
            score+=10
            reasons.append("상단 매도 반전 확인")
        elif bear and body_ratio>=.60:
            score+=7
            reasons.append("강한 하락 캔들 확인")
        else:return None

        if ch15<-1.0:return None

    # 모멘텀 15
    if direction=="LONG":
        if .03<=ch15<=.70:
            score+=5
            reasons.append("15분 상승 모멘텀")
        elif 0<=ch15<.03:score+=2

        if .03<=ch60<=1.0:
            score+=5
            reasons.append("1시간 상승 모멘텀")
        elif 0<=ch60<.03:score+=2

        if ch15>0:score+=5
    else:
        if -.70<=ch15<=-.03:
            score+=5
            reasons.append("15분 하락 모멘텀")
        elif -.03<ch15<=0:score+=2

        if -1.0<=ch60<=-.03:
            score+=5
            reasons.append("1시간 하락 모멘텀")
        elif -.03<ch60<=0:score+=2

        if ch15<0:score+=5

    # RSI 10
    if direction=="LONG":
        if 43<=rsi<=61:
            score+=6
            reasons.append("RSI 과열 없는 진입")
        elif 38<=rsi<43 or 61<rsi<=64:score+=3

        if 42<=rsih<=64:score+=4
        elif 37<=rsih<42 or 64<rsih<=67:score+=2
    else:
        if 37<=rsi<=55:
            score+=6
            reasons.append("RSI 과매도 아닌 진입")
        elif 34<=rsi<37 or 55<rsi<=60:score+=3

        if 32<=rsih<=55:score+=4
        elif 32<=rsih<35 or 55<rsih<=60:score+=2

    # 추세 강도 10
    if adx>=32:
        score+=6
        reasons.append("15분 추세 강도 강함")
    elif adx>=27:score+=4
    else:score+=2

    if adxh>=30:
        score+=4
        reasons.append("1시간 추세 강도 강함")
    elif adxh>=23:score+=2

    # 거래량 10
    if vr>=1.50:
        score+=10
        reasons.append("거래량 급증")
    elif vr>=1.15:
        score+=7
        reasons.append("거래량 증가")
    elif vr>=.90:
        score+=4
    else:
        return None

    # 변동성 5
    if .35<=atr_pct<=1.50:score+=5
    elif .20<=atr_pct<=2.0:score+=3
    else:score+=1

    score=max(0,min(100,int(score)))

    # 진입 타이밍 최소조건
    if timing<12:return None
    if score<MIN_SCORE:return None

    # 과도하게 진행된 추세는 강제 감점
    if direction=="LONG":
        if rsih>64:score=min(score,88)
        if d20>.75:score=min(score,87)
    else:
        if rsih<35:score=min(score,88)
        if d20<-.75:score=min(score,87)

    # 리스크
    risk=max(atr*1.15,p*.0055)
    risk_pct=risk/p*100
    if risk_pct>2.7:return None

    if direction=="LONG":
        sl=p-risk
        tp1=p+risk*1.5
        tp2=p+risk*2.5
    else:
        sl=p+risk
        tp1=p-risk*1.5
        tp2=p-risk*2.5

    if atr_pct>=2:lev=3
    elif atr_pct>=1.5:lev=5
    elif atr_pct>=.9:lev=7
    else:lev=8

    strong=(
        score>=STRONG_SCORE and
        timing>=15 and
        adx>=28 and
        adxh>=22 and
        vr>=.90
    )

    return {
        "symbol":symbol(r),
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
        "vr":vr,
        "lev":lev,
        "setup":setup,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 A+ STRONG ENTRY" if s["strong"] else "⚡ A ENTRY"

    seen=set()
    rr=[]
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
        "🧠 WHY NOW?\n"+
        "\n".join(f"• {x}" for x in rr[:7])+
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
    entry=p.get("entry",0)
    sl=p.get("sl",0)
    tp1=p.get("tp1",0)
    tp2=p.get("tp2",0)

    if kind=="TP1":
        return (
            "🎯 TP1 HIT\n\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
            f"💰 Entry : {fmt(entry)}\n"
            f"🎯 TP1 : {fmt(tp1)}\n\n"
            "🔒 SL → ENTRY\n"
            "원금 방어 모드로 전환합니다."
        )

    if kind=="TP2":
        return (
            "🎯 TP2 HIT\n\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
            f"🎯 TP2 : {fmt(tp2)}\n\n"
            "✅ 목표 구간 도달\n"
            "포지션 추적 종료."
        )

    return (
        "🛑 STOP LOSS\n\n"
        f"🪙 #{sym}\n"
        f"📌 {'LONG 🟢' if d=='LONG' else 'SHORT 🔴'}\n"
        f"💰 Entry : {fmt(entry)}\n"
        f"🛑 SL : {fmt(sl)}\n\n"
        "포지션 추적 종료."
    )

def check_positions(state,rs):
    by={symbol(r):r for r in rs}
    remove=[]

    for sym,p in list(state["positions"].items()):
        if not isinstance(p,dict):
            remove.append(sym)
            continue

        p.setdefault("symbol",sym)
        p.setdefault("tp1_hit",False)

        if any(k not in p for k in ("direction","entry","sl","tp1","tp2")):
            print("INVALID POSITION:",sym)
            remove.append(sym)
            continue

        r=by.get(sym)
        if not r:continue

        price=val(r,3)
        d=p["direction"]

        if d=="LONG":
            if price>=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue
            if price<=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue
            if not p["tp1_hit"] and price>=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
        else:
            if price<=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue
            if price>=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue
            if not p["tp1_hit"] and price<=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))

    for x in remove:
        state["positions"].pop(x,None)

def main():
    print("====================================")
    print(" BTCC REAL FUTURES A+ ENTRY BOT")
    print("====================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=rows()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg("⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패")
        return

    state=load()
    check_positions(state,rs)

    trend=0
    qualified=[]
    rejected=0

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

            bull=e20h>e50h>e100h and ph>e20h and e20>e50>e100 and p>e20
            bear=e20h<e50h<e100h and ph<e20h and e20<e50<e100 and p<e20

            if bull or bear:trend+=1

            s=analyze(r)
            if s:qualified.append(s)
            else:rejected+=1
        except Exception as e:
            print("ANALYZE ERROR:",e)

    qualified.sort(
        key=lambda x:(x["strong"],x["score"],x["vr"],x["adx"]),
        reverse=True
    )

    print("TREND CANDIDATES:",trend)
    print("A ENTRY QUALIFIED:",len(qualified))
    print("REJECTED:",rejected)
    print("ACTIVE:",len(state["positions"]))

    sent=0
    ts=time.time()

    for s in qualified:
        if sent>=MAX_ALERTS:break

        sym=s["symbol"]

        if sym in state["positions"]:continue

        key=f"{sym}:{s['direction']}"
        last=float(state["signals"].get(key,0) or 0)

        if ts-last<COOLDOWN*60:continue

        if not tg(signal_msg(s)):continue

        state["signals"][key]=ts

        state["positions"][sym]={
            "symbol":sym,
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
