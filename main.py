import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MAX_ALERTS=3
COOLDOWN=240
MIN_SCORE=82

COL=[
"open|15","high|15","low|15","close|15","volume|15",
"EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"open|60","high|60","low|60","close|60","volume|60",
"EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60","ATR|60",
"change|15","change|60"
]

HEAD={
    "User-Agent":"Mozilla/5.0",
    "Origin":"https://www.tradingview.com",
    "Referer":"https://www.tradingview.com/",
    "Content-Type":"application/json"
}

def now(): return datetime.now(KST)

def load():
    try:
        with open(STATE_FILE,encoding="utf-8") as f:s=json.load(f)
    except:
        s={"positions":{},"signals":{}}
    s.setdefault("positions",{})
    s.setdefault("signals",{})
    return s

def save(s):
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:
        json.dump(s,f,ensure_ascii=False,indent=2)
    os.replace(STATE_FILE+".tmp",STATE_FILE)

def tg(msg,label="MSG"):
    if not TOKEN or not CHAT_ID:
        print("TG CONFIG ERROR")
        return False
    url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data={"chat_id":CHAT_ID,"text":msg,"disable_web_page_preview":True,"disable_notification":False}
    for n in range(2):
        try:
            r=requests.post(url,json=data,timeout=20)
            try:j=r.json()
            except:j={}
            print(f"TG {label}: http={r.status_code} ok={j.get('ok')} message_id={j.get('result',{}).get('message_id')} desc={j.get('description','')}")
            if r.status_code==200 and j.get("ok") is True:return True
        except Exception as e:print("TG ERROR:",e)
        if n==0:time.sleep(1)
    return False

def rows():
    q={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[{"left":"exchange","operation":"equal","right":"BTCC"}],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    }
    try:
        r=requests.post(TV,json=q,headers=HEAD,timeout=25)
        print("TV:",r.status_code)
        return r.json().get("data",[]) if r.status_code==200 else []
    except Exception as e:
        print("TV ERROR:",e);return []

def v(r,i):
    try:return float(r["d"][i])
    except:return 0.0

def symbol(r):
    return str(r.get("s","")).split(":")[-1].replace(".P","")

def fmt(x):
    if x>=1000:return f"{x:,.2f}"
    if x>=1:return f"{x:.4f}"
    if x>=.01:return f"{x:.5f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def analyze(r,st):
    p,o,h,l=[v(r,i) for i in (3,0,1,2)]
    e20,e50,e100,rs,adx,atr=[v(r,i) for i in (5,6,7,8,9,10)]
    ph,e20h,e50h,e100h,rsh,adxh,atrh=[v(r,i) for i in (14,16,17,18,19,20,21)]
    ch15,ch60=[v(r,i) for i in (22,23)]

    if min(p,e20,e50,e100,e20h,e50h,e100h,atr,atrh)<=0:
        st["data"]+=1;return

    atrp=atr/p*100
    atrph=atrh/ph*100
    d20=(p-e20)/e20*100

    # 변동성 없는 종목 제거
    if atrp<0.18 or atrph<0.15:
        st["dead"]+=1;return

    # 너무 과격한 종목 제거
    if atrp>3.5 or atrph>4.5:
        st["volatile"]+=1;return

    bull=e20h>e50h>e100h and e20>e50>e100 and ph>e20h
    bear=e20h<e50h<e100h and e20<e50<e100 and ph<e20h

    if not bull and not bear:
        st["trend"]+=1;return

    direction="LONG" if bull else "SHORT"

    # 현재봉 구조
    rng=max(h-l,p*.0001)
    body=abs(p-o)/rng
    upper=(h-max(o,p))/rng
    lower=(min(o,p)-l)/rng

    # 최근 눌림 여부를 현재 위치/가격 구조로 확인
    if direction=="LONG":
        pullback=(-.75<=d20<=.25)
        trigger=(p>o and lower>=.12 and body>=.22)
        not_chase=(rsh<67 and rs<68 and ch15<.70 and ch60<1.20 and d20<.65)
        momentum=(ch15>=-.25 and ch15<=.70 and ch60>=-.70)
        rsi_ok=34<=rs<=67 and 35<=rsh<=66
    else:
        pullback=(-.25<=d20<=.75)
        trigger=(p<o and upper>=.12 and body>=.22)
        not_chase=(rsh>33 and rs>32 and ch15>-.70 and ch60>-1.20 and d20>-.65)
        momentum=(ch15>=-.70 and ch15<=.25 and ch60<=.70)
        rsi_ok=33<=rs<=66 and 34<=rsh<=65

    if not pullback:
        st["location"]+=1;return
    if not trigger:
        st["trigger"]+=1;return
    if not not_chase:
        st["chase"]+=1;return
    if not momentum:
        st["momentum"]+=1;return
    if not rsi_ok:
        st["rsi"]+=1;return

    # 추세 강도
    if adx<20 or adxh<18:
        st["adx"]+=1;return

    trend=0
    if direction=="LONG":
        trend=22
        if ph>e20h:trend+=2
        if p>e20:trend+=1
    else:
        trend=22
        if ph<e20h:trend+=2
        if p<e20:trend+=1

    location=0
    if abs(d20)<=.25:location=20
    elif abs(d20)<=.45:location=17
    else:location=14

    timing=14
    if body>=.35:timing+=3
    if direction=="LONG" and lower>=.18:timing+=4
    if direction=="SHORT" and upper>=.18:timing+=4
    if abs(ch15)<=.35:timing+=2
    timing=min(23,timing)

    rscore=0
    if direction=="LONG":
        if 42<=rs<=62:rscore+=5
        elif 36<=rs<42 or 62<rs<=67:rscore+=3
        if 40<=rsh<=60:rscore+=5
        elif 35<=rsh<40 or 60<rsh<=65:rscore+=3
    else:
        if 38<=rs<=57:rscore+=5
        elif 33<=rs<38 or 57<rs<=63:rscore+=3
        if 38<=rsh<=58:rscore+=5
        elif 34<=rsh<38 or 58<rsh<=64:rscore+=3

    adscore=0
    if adx>=30:adscore+=5
    elif adx>=24:adscore+=4
    elif adx>=20:adscore+=3
    if adxh>=30:adscore+=5
    elif adxh>=24:adscore+=4
    elif adxh>=18:adscore+=3

    volscore=0
    if .30<=atrp<=1.80:volscore=5
    elif .18<=atrp<.30 or 1.80<atrp<=2.50:volscore=3
    else:volscore=1

    momscore=5
    if abs(ch15)<=.35:momscore+=3
    if abs(ch60)<=.80:momscore+=2

    score=trend+location+timing+rscore+adscore+volscore+momscore

    # 추격 위험 추가 차감
    penalty=0
    if direction=="LONG":
        if d20>.40:penalty+=5
        if ch15>.45:penalty+=5
        if rsh>62:penalty+=3
    else:
        if d20<-.40:penalty+=5
        if ch15<-.45:penalty+=5
        if rsh<38:penalty+=3

    score-=penalty

    # 완벽점수 방지 및 실제 조건 차별화
    score=min(score,97)
    if timing<20:score=min(score,92)
    if location<18:score=min(score,93)
    if rscore<8:score=min(score,91)
    if adscore<8:score=min(score,92)

    if score<MIN_SCORE:
        st["score"]+=1;return

    quality="A+" if score>=91 and timing>=19 and location>=17 and penalty<=3 else "A"
    if quality=="A" and score<85:
        st["grade"]+=1;return

    risk=max(atr*1.20,p*.0045)
    riskpct=risk/p*100
    if riskpct<.35 or riskpct>3:
        st["risk"]+=1;return

    if direction=="LONG":
        sl=p-risk
        tp1=p+risk*1.5
        tp2=p+risk*2.5
        setup="눌림 후 상승 재진입"
    else:
        sl=p+risk
        tp1=p-risk*1.5
        tp2=p-risk*2.5
        setup="반등 후 하락 재진입"

    lev=8 if atrp<.8 else 6 if atrp<1.4 else 4 if atrp<2 else 3

    reasons=[
        "1H 추세 방향 일치",
        "EMA20 눌림 구간",
        "현재봉 방향 전환 확인",
        "가격 반응 트리거 확인",
        "RSI 추격 구간 아님",
        "변동성 조건 충족"
    ]

    return {
        "symbol":symbol(r),"direction":direction,"score":score,
        "quality":quality,"price":p,"sl":sl,"tp1":tp1,"tp2":tp2,
        "rsi":rs,"rsh":rsh,"adx":adx,"adxh":adxh,
        "ch15":ch15,"ch60":ch60,"atrp":atrp,
        "trend":trend,"location":location,"timing":timing,
        "rscore":rscore,"adscore":adscore,"momscore":momscore,
        "volscore":volscore,"penalty":penalty,"lev":lev,
        "setup":setup,"reasons":reasons
    }

def msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
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
        "🎯 QUALITY\n"
        f"├ Trend : {s['trend']}/25\n"
        f"├ Location : {s['location']}/20\n"
        f"├ Timing : {s['timing']}/23\n"
        f"├ RSI : {s['rscore']}/10\n"
        f"├ ADX : {s['adscore']}/10\n"
        f"├ Momentum : {s['momscore']}/10\n"
        f"└ Volatility : {s['volscore']}/5\n"
        f"Penalty : -{s['penalty']}\n\n"
        "🧠 ENTRY REASONS\n"+
        "\n".join("• "+x for x in s["reasons"])+
        "\n\n⚙️ RISK\n"
        f"├ Leverage : {s['lev']}x\n"
        "├ TP1 → SL = ENTRY\n"
        "└ TP2 → TRACKING END\n\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ Signal only / No auto order"
    )

def posmsg(p,k):
    d=p.get("direction","LONG")
    sy=p.get("symbol","UNKNOWN")
    if k=="TP1":
        return f"🎯 TP1 HIT\n\n🪙 #{sy}\n📌 {d}\n💰 Entry : {fmt(p['entry'])}\n🎯 TP1 : {fmt(p['tp1'])}\n\n🔒 SL → ENTRY\n원금 방어 모드로 전환"
    if k=="TP2":
        return f"🎯 TP2 HIT\n\n🪙 #{sy}\n📌 {d}\n🎯 TP2 : {fmt(p['tp2'])}\n\n✅ 추적 종료"
    return f"🛑 STOP LOSS\n\n🪙 #{sy}\n📌 {d}\n🛑 SL : {fmt(p['sl'])}\n\n❌ 포지션 추적 종료"

def check(state,rs):
    mp={symbol(r):r for r in rs}
    for key,p in list(state["positions"].items()):
        if not isinstance(p,dict):
            state["positions"].pop(key,None);continue
        p.setdefault("symbol",key)
        if not all(x in p for x in ("entry","sl","tp1","tp2","direction")):
            state["positions"].pop(key,None);continue
        r=mp.get(p["symbol"])
        if not r:continue
        price=v(r,3)
        long=p["direction"]=="LONG"

        if long and price>=p["tp2"] or not long and price<=p["tp2"]:
            tg(posmsg(p,"TP2"),f"{p['symbol']} TP2")
            state["positions"].pop(key,None);continue

        if long and price<=p["sl"] or not long and price>=p["sl"]:
            tg(posmsg(p,"SL"),f"{p['symbol']} SL")
            state["positions"].pop(key,None);continue

        if not p.get("tp1_hit",False) and (price>=p["tp1"] if long else price<=p["tp1"]):
            p["tp1_hit"]=True
            p["sl"]=p["entry"]
            tg(posmsg(p,"TP1"),f"{p['symbol']} TP1")

def main():
    print("===================================")
    print(" BTCC FUTURES FINAL ENTRY BOT")
    print("===================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR");return

    rs=rows()
    print("BTCC REAL ROWS:",len(rs))
    if not rs:
        tg("⚠️ BTCC DATA ERROR\n\nBTCC TradingView 데이터 조회 실패","DATA ERROR")
        return

    state=load()
    check(state,rs)

    st={k:0 for k in [
        "data","dead","volatile","trend","location","trigger",
        "chase","momentum","rsi","adx","score","grade","risk"
    ]}

    candidates=[]
    for r in rs:
        try:
            s=analyze(r,st)
            if s:candidates.append(s)
        except Exception as e:
            st["data"]+=1
            print("ANALYZE ERROR:",e)

    candidates.sort(
        key=lambda x:(1 if x["quality"]=="A+" else 0,x["score"],x["timing"],x["location"]),
        reverse=True
    )

    print("QUALIFIED:",len(candidates))
    print("FILTER STATS:",st)

    for i,s in enumerate(candidates[:10],1):
        print(
            f"#{i} {s['symbol']} {s['direction']} "
            f"{s['quality']} SCORE={s['score']} "
            f"T={s['timing']} L={s['location']} "
            f"ATR={s['atrp']:.2f}%"
        )

    sent=0
    t=time.time()

    for s in candidates:
        if sent>=MAX_ALERTS:break
        key=s["symbol"]

        if key in state["positions"]:
            print("SKIP ACTIVE:",key);continue

        sid=f"{key}:{s['direction']}"
        if t-float(state["signals"].get(sid,0) or 0)<COOLDOWN*60:
            print("SKIP COOLDOWN:",key);continue

        if not tg(msg(s),f"{key} {s['direction']} {s['quality']}"):
            print("SEND FAILED:",key);continue

        state["signals"][sid]=t
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
        print("SIGNAL SENT:",key,s["quality"],s["score"])
        time.sleep(.7)

    save(state)
    print("FINAL SIGNALS:",sent)
    print("ACTIVE:",len(state["positions"]))
    print("DONE")

if __name__=="__main__":
    main()
