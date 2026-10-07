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
"close|15","volume|15","EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"close|60","volume|60","EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60","ATR|60",
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
            json={
                "chat_id":CHAT_ID,
                "text":msg,
                "disable_web_page_preview":True
            },
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
    p15=val(row,0)
    v15=val(row,1)
    e20=val(row,2)
    e50=val(row,3)
    e100=val(row,4)
    rsi=val(row,5)
    adx=val(row,6)
    atr=val(row,7)

    p60=val(row,8)
    v60=val(row,9)
    e20h=val(row,10)
    e50h=val(row,11)
    e100h=val(row,12)
    rsih=val(row,13)
    adxh=val(row,14)

    ch15=val(row,16)
    ch60=val(row,17)

    if min(p15,e20,e50,e100,p60,e20h,e50h,e100h,atr)<=0:
        return None

    atr_pct=atr/p15*100
    dist20=(p15-e20)/e20*100
    dist50=(p15-e50)/e50*100

    bull_h=e20h>e50h>e100h and p60>e20h
    bear_h=e20h<e50h<e100h and p60<e20h
    bull15=p15>e20>e50 and p15>e100
    bear15=p15<e20<e50 and p15<e100

    if bull_h and bull15:
        direction="LONG"
    elif bear_h and bear15:
        direction="SHORT"
    else:
        return None

    if adx<20 or adxh<17:
        return None

    if direction=="LONG":
        if rsi>=73 or rsih>=75:
            return None
        if rsi<=32 and rsih<=35:
            return None
        if dist20>2.0 or dist50>3.5:
            return None
    else:
        if rsi<=27 or rsih<=27:
            return None
        if rsi>=68 and rsih>=65:
            return None
        if dist20<-2.0 or dist50<-3.5:
            return None

    score=0
    reasons=[]
    setup=""
    timing=0

    # 1H TREND 20
    if direction=="LONG":
        if e20h>e50h>e100h:
            score+=12
        if p60>e20h:
            score+=5
        if p60-e20h>0:
            score+=3
        reasons.append("1시간 상승 추세 정렬")
    else:
        if e20h<e50h<e100h:
            score+=12
        if p60<e20h:
            score+=5
        if p60-e20h<0:
            score+=3
        reasons.append("1시간 하락 추세 정렬")

    # 15M TREND 15
    if direction=="LONG":
        if e20>e50:
            score+=6
        if e50>e100:
            score+=5
        if p15>e20:
            score+=4
        reasons.append("15분 단기 추세 정렬")
    else:
        if e20<e50:
            score+=6
        if e50<e100:
            score+=5
        if p15<e20:
            score+=4
        reasons.append("15분 단기 추세 정렬")

    # RSI 10
    if direction=="LONG":
        if 50<=rsi<=63:
            score+=6
            reasons.append("15분 RSI 진입 구간")
        elif 46<=rsi<50 or 63<rsi<=67:
            score+=3

        if 48<=rsih<=65:
            score+=4
            reasons.append("1시간 RSI 상승 여력")
        elif 44<=rsih<48 or 65<rsih<=68:
            score+=2
    else:
        if 37<=rsi<=50:
            score+=6
            reasons.append("15분 RSI 진입 구간")
        elif 33<=rsi<37 or 50<rsi<=54:
            score+=3

        if 34<=rsih<=52:
            score+=4
            reasons.append("1시간 RSI 하락 여력")
        elif 30<=rsih<34 or 52<rsih<=56:
            score+=2

    # ADX 10
    if adx>=30:
        score+=6
        reasons.append("15분 추세 강도 강함")
    elif adx>=24:
        score+=4
    else:
        score+=2

    if adxh>=25:
        score+=4
        reasons.append("1시간 추세 강도 확인")
    elif adxh>=20:
        score+=2

    # MOMENTUM 10
    if direction=="LONG":
        if 0.10<=ch15<=0.90:
            score+=5
            reasons.append("15분 상승 모멘텀")
        elif 0<=ch15<0.10:
            score+=2

        if 0.05<=ch60<=0.80:
            score+=5
            reasons.append("1시간 상승 모멘텀")
        elif 0<=ch60<0.05:
            score+=2
    else:
        if -0.90<=ch15<=-0.10:
            score+=5
            reasons.append("15분 하락 모멘텀")
        elif -0.10<ch15<=0:
            score+=2

        if -0.80<=ch60<=-0.05:
            score+=5
            reasons.append("1시간 하락 모멘텀")
        elif -0.05<ch60<=0:
            score+=2

    # ENTRY TIMING 25
    if direction=="LONG":
        if 0.05<=dist20<=0.55 and rsi>=48:
            timing=25
            setup="EMA20 눌림 후 재상승"
            reasons.append("EMA20 인근 눌림 진입 위치")
        elif 0<=dist20<=0.85 and ch15>=0.10:
            timing=20
            setup="추세 재개"
            reasons.append("EMA20 위 재상승 확인")
        elif 0.85<dist20<=1.30 and ch15>=0.20:
            timing=12
            setup="초기 돌파"
            reasons.append("단기 돌파 모멘텀")
        elif -0.30<=dist20<0.05 and ch15>0:
            timing=18
            setup="EMA20 회복"
            reasons.append("EMA20 회복 시도")
        else:
            return None
    else:
        if -0.55<=dist20<=-0.05 and rsi<=52:
            timing=25
            setup="EMA20 반등 후 재하락"
            reasons.append("EMA20 인근 반등 후 하락 위치")
        elif -0.85<=dist20<0 and ch15<=-0.10:
            timing=20
            setup="추세 재개"
            reasons.append("EMA20 아래 재하락 확인")
        elif -1.30<=dist20<-0.85 and ch15<=-0.20:
            timing=12
            setup="초기 돌파"
            reasons.append("단기 하락 돌파 모멘텀")
        elif -0.05<dist20<=0.30 and ch15<0:
            timing=18
            setup="EMA20 이탈"
            reasons.append("EMA20 하향 이탈 확인")
        else:
            return None

    score+=timing

    # VOLATILITY / RISK
    if 0.35<=atr_pct<=2.0:
        score+=10
        reasons.append("변동성 및 손절폭 양호")
    elif 0.20<=atr_pct<0.35 or 2.0<atr_pct<=2.8:
        score+=6
    elif atr_pct<3.5:
        score+=3
    else:
        return None

    if v15<50000 or v60<50000:
        return None

    score=min(score,100)

    if score<MIN_SCORE:
        return None

    # 이미 많이 진행된 방향은 강한 신호가 되지 못하게 제한
    if direction=="SHORT" and rsih<34:
        score=min(score,87)

    if direction=="LONG" and rsih>66:
        score=min(score,87)

    if direction=="LONG" and dist20>0.9:
        score=min(score,88)

    if direction=="SHORT" and dist20<-0.9:
        score=min(score,88)

    risk=max(atr*1.15,p15*0.006)
    risk_pct=risk/p15*100

    if risk_pct>3.0:
        return None

    if direction=="LONG":
        sl=p15-risk
        tp1=p15+risk*1.5
        tp2=p15+risk*2.5
    else:
        sl=p15+risk
        tp1=p15-risk*1.5
        tp2=p15-risk*2.5

    if atr_pct>=3.0:
        lev=3
    elif atr_pct>=2.0:
        lev=5
    elif atr_pct>=1.0:
        lev=7
    else:
        lev=8

    strong=(
        score>=STRONG_SCORE and
        timing>=20 and
        adx>=25 and
        adxh>=20
    )

    return {
        "symbol":symbol(row),
        "direction":direction,
        "score":int(score),
        "strong":strong,
        "price":p15,
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
        "lev":lev,
        "setup":setup,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 강한 매매 시그널" if s["strong"] else "⚡ 매매 시그널"

    seen=set()
    reasons=[]
    for x in s["reasons"]:
        if x not in seen:
            reasons.append(x)
            seen.add(x)

    reason_text="\n".join(f"• {x}" for x in reasons[:6])

    return (
        f"{icon} {title}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 종목 : #{s['symbol']}\n"
        f"📌 방향 : {'롱 (LONG)' if s['direction']=='LONG' else '숏 (SHORT)'}\n"
        f"⭐ 신뢰도 : {s['score']}/100\n"
        f"🎯 진입형태 : {s['setup']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 진입 계획\n"
        f"├ 진입가 : {fmt(s['price'])}\n"
        f"├ 손절가 : {fmt(s['sl'])}\n"
        f"├ TP1 : {fmt(s['tp1'])}\n"
        f"└ TP2 : {fmt(s['tp2'])}\n\n"
        "📊 시장 상태\n"
        f"├ RSI 15분 : {s['rsi']:.1f}\n"
        f"├ RSI 1시간 : {s['rsih']:.1f}\n"
        f"├ ADX 15분 : {s['adx']:.1f}\n"
        f"├ ADX 1시간 : {s['adxh']:.1f}\n"
        f"├ 15분 변동 : {s['ch15']:+.2f}%\n"
        f"├ 1시간 변동 : {s['ch60']:+.2f}%\n"
        f"└ ATR 변동성 : {s['atr_pct']:.2f}%\n\n"
        "🧠 진입 근거\n"
        f"{reason_text}\n\n"
        "⚙️ 리스크 관리\n"
        f"├ 권장 레버리지 : {s['lev']}x\n"
        "├ TP1 도달 → SL을 진입가로 이동\n"
        "└ TP2 도달 → 추적 종료\n\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ 자동주문 없음"
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
            "🎯 TP1 도달\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{sym}\n"
            f"📌 방향 : {'롱 (LONG)' if direction=='LONG' else '숏 (SHORT)'}\n"
            f"💰 진입가 : {fmt(entry)}\n"
            f"🎯 TP1 : {fmt(tp1)}\n\n"
            "🔒 손절가 → 진입가 이동\n"
            "이제 본절 이하 손실을 차단합니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    if kind=="TP2":
        return (
            "🎯 TP2 도달\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{sym}\n"
            f"📌 방향 : {'롱 (LONG)' if direction=='LONG' else '숏 (SHORT)'}\n"
            f"💰 진입가 : {fmt(entry)}\n"
            f"🎯 TP2 : {fmt(tp2)}\n\n"
            "✅ 목표가 달성\n"
            "포지션 추적을 종료합니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    return (
        "🛑 손절가 도달\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{sym}\n"
        f"📌 방향 : {'롱 (LONG)' if direction=='LONG' else '숏 (SHORT)'}\n"
        f"💰 진입가 : {fmt(entry)}\n"
        f"🛑 손절가 : {fmt(sl)}\n\n"
        "포지션 추적을 종료합니다.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def check_positions(state,rs):
    by={symbol(r):r for r in rs}
    remove=[]

    for sym,p in list(state["positions"].items()):
        # 구버전 state 호환
        if not isinstance(p,dict):
            remove.append(sym)
            continue

        p.setdefault("symbol",sym)
        p.setdefault("tp1_hit",False)

        if "direction" not in p or "entry" not in p:
            print("INVALID POSITION:",sym)
            remove.append(sym)
            continue

        r=by.get(sym)

        if not r:
            continue

        price=val(r,0)
        direction=p["direction"]

        if direction=="LONG":
            if price>=p.get("tp2",float("inf")):
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue

            if price<=p.get("sl",-float("inf")):
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue

            if not p.get("tp1_hit") and price>=p.get("tp1",float("inf")):
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
                time.sleep(.5)

        else:
            if price<=p.get("tp2",-float("inf")):
                tg(position_msg(p,"TP2"))
                remove.append(sym)
                continue

            if price>=p.get("sl",float("inf")):
                tg(position_msg(p,"SL"))
                remove.append(sym)
                continue

            if not p.get("tp1_hit") and price<=p.get("tp1",-float("inf")):
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(position_msg(p,"TP1"))
                time.sleep(.5)

    for sym in remove:
        state["positions"].pop(sym,None)

def main():
    print("====================================")
    print(" BTCC REAL FUTURES ENTRY BOT")
    print("====================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=rows()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg(
            "⚠️ BTCC 데이터 조회 실패\n\n"
            "TradingView BTCC 선물 데이터가 응답하지 않았습니다."
        )
        return

    state=load()
    check_positions(state,rs)

    trend_candidates=0
    candidates=[]

    for r in rs:
        try:
            p15=val(r,0)
            e20=val(r,2)
            e50=val(r,3)
            e100=val(r,4)
            p60=val(r,8)
            e20h=val(r,10)
            e50h=val(r,11)
            e100h=val(r,12)

            bull=(
                e20h>e50h>e100h and
                p60>e20h and
                p15>e20>e50 and
                p15>e100
            )

            bear=(
                e20h<e50h<e100h and
                p60<e20h and
                p15<e20<e50 and
                p15<e100
            )

            if bull or bear:
                trend_candidates+=1

            s=analyze(r)

            if s:
                candidates.append(s)

        except Exception as e:
            print("ANALYZE ERROR:",e)

    candidates.sort(
        key=lambda x:(x["strong"],x["score"]),
        reverse=True
    )

    print("TREND CANDIDATES:",trend_candidates)
    print("ENTRY QUALIFIED:",len(candidates))
    print("ACTIVE:",len(state["positions"]))

    sent=0
    now_ts=time.time()

    for s in candidates:
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
