import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=82
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
        with open(STATE_FILE,encoding="utf-8") as f:
            s=json.load(f)
    except:
        s={"positions":{},"signals":{}}
    s.setdefault("positions",{})
    s.setdefault("signals",{})
    return s

def save(s):
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:
        json.dump(s,f,ensure_ascii=False,indent=2)
    os.replace(STATE_FILE+".tmp",STATE_FILE)

def tg(msg):
    if not TOKEN or not CHAT_ID:
        print("TELEGRAM CONFIG ERROR")
        return False
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
        if r.status_code!=200:
            print(r.text[:500])
            return []
        return r.json().get("data",[])
    except Exception as e:
        print("TV ERROR:",e)
        return []

def rows():
    payload={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[
            {"left":"exchange","operation":"equal","right":"BTCC"}
        ],
        "columns":COL,
        "sort":{
            "sortBy":"volume|15",
            "sortOrder":"desc"
        },
        "range":[0,500]
    }
    return tv(payload)

def val(row,i):
    try:
        return float(row["d"][i])
    except:
        return 0.0

def symbol(row):
    return str(row.get("s","")).split(":")[-1].replace(".P","")

def fmt(x):
    if x>=1000:
        return f"{x:,.2f}"
    if x>=1:
        return f"{x:.4f}"
    if x>=0.01:
        return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def analyze(row):
    o=val(row,0)
    h=val(row,1)
    l=val(row,2)
    p=val(row,3)
    v=val(row,4)
    e20=val(row,5)
    e50=val(row,6)
    e100=val(row,7)
    rsi=val(row,8)
    adx=val(row,9)
    atr=val(row,10)

    oh=val(row,11)
    hh=val(row,12)
    lh=val(row,13)
    ph=val(row,14)
    vh=val(row,15)
    e20h=val(row,16)
    e50h=val(row,17)
    e100h=val(row,18)
    rsih=val(row,19)
    adxh=val(row,20)

    ch15=val(row,21)
    ch60=val(row,22)

    if min(o,h,l,p,e20,e50,e100,ph,e20h,e50h,e100h,atr)<=0:
        return None

    atr_pct=atr/p*100
    dist20=(p-e20)/e20*100
    dist50=(p-e50)/e50*100

    candle_range=h-l
    body=abs(p-o)

    if candle_range<=0:
        return None

    upper_wick=h-max(o,p)
    lower_wick=min(o,p)-l
    body_ratio=body/candle_range

    bull_candle=p>o
    bear_candle=p<o

    upper_rejection=upper_wick/candle_range
    lower_rejection=lower_wick/candle_range

    bull_h=e20h>e50h>e100h and ph>e20h
    bear_h=e20h<e50h<e100h and ph<e20h

    bull15=e20>e50>e100 and p>e20
    bear15=e20<e50<e100 and p<e20

    if bull_h and bull15:
        direction="LONG"
    elif bear_h and bear15:
        direction="SHORT"
    else:
        return None

    # 기본 시장 품질 필터
    if adx<22 or adxh<18:
        return None

    if v<100000 or vh<100000:
        return None

    if atr_pct<0.20 or atr_pct>2.8:
        return None

    # 추격 진입 차단
    if direction=="LONG":
        if rsi>=70 or rsih>=73:
            return None
        if rsi<=30:
            return None
        if dist20>1.35 or dist50>3.0:
            return None
    else:
        if rsi<=30 or rsih<=27:
            return None
        if rsi>=70:
            return None
        if dist20<-1.35 or dist50<-3.0:
            return None

    score=0
    reasons=[]
    setup=""
    timing=0

    # ==================================================
    # 1. 추세 구조 : 25점
    # ==================================================
    if direction=="LONG":
        if e20h>e50h>e100h:
            score+=12
            reasons.append("1시간 EMA 상승 배열")
        if ph>e20h:
            score+=3
            reasons.append("1시간 가격이 EMA20 위")
        if e20>e50>e100:
            score+=7
            reasons.append("15분 EMA 상승 배열")
        if p>e20:
            score+=3
    else:
        if e20h<e50h<e100h:
            score+=12
            reasons.append("1시간 EMA 하락 배열")
        if ph<e20h:
            score+=3
            reasons.append("1시간 가격이 EMA20 아래")
        if e20<e50<e100:
            score+=7
            reasons.append("15분 EMA 하락 배열")
        if p<e20:
            score+=3

    # ==================================================
    # 2. 실제 진입 위치 : 25점
    # ==================================================
    if direction=="LONG":
        # EMA20 근처에서 다시 위로 올라오는 자리
        if -0.25<=dist20<=0.45:
            score+=15
            timing=15
            setup="EMA20 눌림 후 재상승"
            reasons.append("EMA20 인근 눌림 진입 위치")
        elif 0.45<dist20<=0.85:
            score+=10
            timing=10
            setup="추세 재개"
            reasons.append("EMA20 위 추세 재개")
        elif -0.45<=dist20<-0.25:
            score+=8
            timing=8
            setup="EMA20 회복 시도"
            reasons.append("EMA20 회복 구간")
        else:
            return None

        # 현재봉 매수 반전 구조
        if bull_candle and lower_rejection>=0.20 and body_ratio>=0.25:
            score+=10
            reasons.append("15분봉 하단 매수 반전")
        elif bull_candle and body_ratio>=0.55:
            score+=6
            reasons.append("15분 상승 캔들 확인")
        elif lower_rejection>=0.28:
            score+=4
        else:
            score-=4

        # 너무 강하게 이미 오른 봉은 제외
        if ch15>1.20:
            return None

    else:
        # EMA20 근처에서 다시 아래로 내려오는 자리
        if -0.45<=dist20<=0.25:
            score+=15
            timing=15
            setup="EMA20 반등 후 재하락"
            reasons.append("EMA20 인근 반등 실패 구간")
        elif -0.85<=dist20<-0.45:
            score+=10
            timing=10
            setup="추세 재개"
            reasons.append("EMA20 아래 추세 재개")
        elif 0.25<dist20<=0.45:
            score+=8
            timing=8
            setup="EMA20 이탈 시도"
            reasons.append("EMA20 하향 이탈 구간")
        else:
            return None

        # 현재봉 매도 반전 구조
        if bear_candle and upper_rejection>=0.20 and body_ratio>=0.25:
            score+=10
            reasons.append("15분봉 상단 매도 반전")
        elif bear_candle and body_ratio>=0.55:
            score+=6
            reasons.append("15분 하락 캔들 확인")
        elif upper_rejection>=0.28:
            score+=4
        else:
            score-=4

        # 이미 급락한 봉 추격 방지
        if ch15<-1.20:
            return None

    # ==================================================
    # 3. 모멘텀 : 15점
    # ==================================================
    if direction=="LONG":
        if 0.05<=ch15<=0.80:
            score+=6
            reasons.append("15분 상승 모멘텀")
        elif 0<=ch15<0.05:
            score+=3

        if 0.05<=ch60<=1.20:
            score+=5
            reasons.append("1시간 상승 모멘텀")
        elif 0<=ch60<0.05:
            score+=2

        if 0<ch15<ch60+0.8:
            score+=4
    else:
        if -0.80<=ch15<=-0.05:
            score+=6
            reasons.append("15분 하락 모멘텀")
        elif -0.05<ch15<=0:
            score+=3

        if -1.20<=ch60<=-0.05:
            score+=5
            reasons.append("1시간 하락 모멘텀")
        elif -0.05<ch60<=0:
            score+=2

        if ch15<0 and ch15>ch60-0.8:
            score+=4

    # ==================================================
    # 4. RSI : 10점
    # ==================================================
    if direction=="LONG":
        if 45<=rsi<=62:
            score+=6
            reasons.append("RSI 과열 없는 상승 진입")
        elif 40<=rsi<45 or 62<rsi<=66:
            score+=3

        if 45<=rsih<=65:
            score+=4
        elif 40<=rsih<45 or 65<rsih<=68:
            score+=2
    else:
        if 38<=rsi<=55:
            score+=6
            reasons.append("RSI 과매도 아닌 하락 진입")
        elif 34<=rsi<38 or 55<rsi<=60:
            score+=3

        if 30<=rsih<=55:
            score+=4
        elif 27<=rsih<30 or 55<rsih<=60:
            score+=2

    # ==================================================
    # 5. 추세 강도 : 10점
    # ==================================================
    if adx>=32:
        score+=6
        reasons.append("15분 추세 강도 우수")
    elif adx>=26:
        score+=4
    else:
        score+=2

    if adxh>=30:
        score+=4
        reasons.append("1시간 추세 강도 우수")
    elif adxh>=22:
        score+=2

    # ==================================================
    # 6. 거래량 : 10점
    # ==================================================
    volume_ratio=v/max(vh,1)

    if volume_ratio>=1.50:
        score+=10
        reasons.append("15분 거래량 급증")
    elif volume_ratio>=1.15:
        score+=7
        reasons.append("15분 거래량 증가")
    elif volume_ratio>=0.85:
        score+=4
    else:
        score+=1

    # ==================================================
    # 7. 리스크 : 5점
    # ==================================================
    if 0.35<=atr_pct<=1.50:
        score+=5
    elif 0.20<=atr_pct<0.35 or 1.50<atr_pct<=2.20:
        score+=3
    else:
        score+=1

    # 100점 고정 구조
    score=max(0,min(100,int(score)))

    # 실제 진입 타이밍이 약하면 무조건 제외
    if timing<10:
        return None

    # 최소 점수
    if score<MIN_SCORE:
        return None

    # 강한 추세라도 RSI가 이미 끝까지 간 경우 점수 제한
    if direction=="LONG":
        if rsih>67:
            score=min(score,86)
        if dist20>0.90:
            score=min(score,87)
    else:
        if rsih<32:
            score=min(score,86)
        if dist20<-0.90:
            score=min(score,87)

    # 실제 리스크
    risk=max(atr*1.15,p*0.0055)
    risk_pct=risk/p*100

    if risk_pct>2.8:
        return None

    if direction=="LONG":
        sl=p-risk
        tp1=p+risk*1.5
        tp2=p+risk*2.5
    else:
        sl=p+risk
        tp1=p-risk*1.5
        tp2=p-risk*2.5

    if atr_pct>=2.0:
        lev=3
    elif atr_pct>=1.50:
        lev=5
    elif atr_pct>=0.90:
        lev=7
    else:
        lev=8

    strong=(
        score>=STRONG_SCORE and
        timing>=15 and
        adx>=28 and
        adxh>=22 and
        volume_ratio>=0.85
    )

    return {
        "symbol":symbol(row),
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
        "atr":atr,
        "atr_pct":atr_pct,
        "volume_ratio":volume_ratio,
        "lev":lev,
        "setup":setup,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 STRONG ENTRY" if s["strong"] else "⚡ ENTRY SIGNAL"

    seen=set()
    rr=[]
    for x in s["reasons"]:
        if x not in seen:
            rr.append(x)
            seen.add(x)

    reason_text="\n".join(f"• {x}" for x in rr[:7])

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
        "🧠 WHY NOW?\n"
        f"{reason_text}\n\n"
        "⚙️ RISK\n"
        f"├ Leverage : {s['lev']}x\n"
        "├ TP1 → SL = ENTRY\n"
        "└ TP2 → TRACKING END\n\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ Signal only / No auto order"
    )

def position_msg(p,kind):
    sym=p.get("symbol","UNKNOWN")
    direction=p.get("direction","LONG")
    entry=p.get("entry",0)
    sl=p.get("sl",0)
    tp1=p.get("tp1",0)
    tp2=p.get("tp2",0)

    if kind=="TP1":
        return (
            "🎯 TP1 HIT\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if direction=='LONG' else 'SHORT 🔴'}\n"
            f"💰 Entry : {fmt(entry)}\n"
            f"🎯 TP1 : {fmt(tp1)}\n\n"
            "🔒 SL → ENTRY\n"
            "원금 방어 모드로 전환합니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    if kind=="TP2":
        return (
            "🎯 TP2 HIT\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{sym}\n"
            f"📌 {'LONG 🟢' if direction=='LONG' else 'SHORT 🔴'}\n"
            f"💰 Entry : {fmt(entry)}\n"
            f"🎯 TP2 : {fmt(tp2)}\n\n"
            "✅ 목표 구간 도달\n"
            "포지션 추적 종료.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    return (
        "🛑 STOP LOSS\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{sym}\n"
        f"📌 {'LONG 🟢' if direction=='LONG' else 'SHORT 🔴'}\n"
        f"💰 Entry : {fmt(entry)}\n"
        f"🛑 SL : {fmt(sl)}\n\n"
        "포지션 추적 종료.\n"
        "━━━━━━━━━━━━━━━━━━━━"
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

        required=("direction","entry","sl","tp1","tp2")
        if any(k not in p for k in required):
            print("INVALID POSITION:",sym)
            remove.append(sym)
            continue

        r=by.get(sym)
        if not r:
            continue

        price=val(r,3)
        direction=p["direction"]

        if direction=="LONG":
            if price>=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue

            if price<=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue

            if not p.get("tp1_hit") and price>=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
                time.sleep(.5)

        else:
            if price<=p["tp2"]:
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue

            if price>=p["sl"]:
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue

            if not p.get("tp1_hit") and price<=p["tp1"]:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
                time.sleep(.5)

    for sym in remove:
        state["positions"].pop(sym,None)

def main():
    print("====================================")
    print(" BTCC REAL FUTURES PRECISION BOT")
    print("====================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=rows()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg(
            "⚠️ BTCC DATA ERROR\n\n"
            "BTCC TradingView 데이터 조회 실패"
        )
        return

    state=load()
    check_positions(state,rs)

    trend_candidates=0
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

            if bull or bear:
                trend_candidates+=1

            s=analyze(r)

            if s:
                qualified.append(s)
            else:
                rejected+=1

        except Exception as e:
            print("ANALYZE ERROR:",e)

    # 점수뿐 아니라 실제 진입 타이밍과 거래량을 우선
    qualified.sort(
        key=lambda x:(
            x["strong"],
            x["score"],
            x["volume_ratio"],
            x["adx"],
            x["timing"] if "timing" in x else 0
        ),
        reverse=True
    )

    print("TREND CANDIDATES:",trend_candidates)
    print("ENTRY QUALIFIED:",len(qualified))
    print("REJECTED:",rejected)
    print("ACTIVE:",len(state["positions"]))

    sent=0
    now_ts=time.time()

    for s in qualified:
        if sent>=MAX_ALERTS:
            break

        sym=s["symbol"]

        if sym in state["positions"]:
            continue

        key=f"{sym}:{s['direction']}"
        last=float(state["signals"].get(key,0) or 0)

        if now_ts-last<COOLDOWN*60:
            continue

        if not tg(signal_msg(s)):
            continue

        state["signals"][key]=now_ts

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
        time.sleep(.8)

    save(state)

    print("FINAL SIGNALS:",sent)
    print("ACTIVE:",len(state["positions"]))
    print("DONE")

if __name__=="__main__":
    main()
