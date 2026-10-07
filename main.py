# main.py
import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"

MIN_SCORE=84
STRONG_SCORE=92
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
            return []
        return r.json().get("data",[])
    except Exception as e:
        print("TV ERROR:",e)
        return []

def rows():
    payload={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[{"left":"exchange","operation":"equal","right":"BTCC"}],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    }
    return tv(payload)

def val(row,i):
    try:
        return float(row["d"][i])
    except:
        return 0.0

def symbol(row):
    s=str(row.get("s",""))
    s=s.split(":")[-1]
    return s.replace(".P","")

def fmt(x):
    if x>=1000:return f"{x:,.2f}"
    if x>=1:return f"{x:.4f}"
    if x>=0.01:return f"{x:.5f}"
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
    atrh=val(row,15)

    ch15=val(row,16)
    ch60=val(row,17)

    if min(p15,e20,e50,e100,p60,e20h,e50h,e100h,atr)>0:
        pass
    else:
        return None

    bull_h=e20h>e50h>e100h and p60>e20h
    bear_h=e20h<e50h<e100h and p60<e20h
    bull_15=p15>e20>e50 and p15>e100
    bear_15=p15<e20<e50 and p15<e100

    if not ((bull_h and bull_15) or (bear_h and bear_15)):
        return None

    direction="LONG" if bull_h and bull_15 else "SHORT"

    if adx<22 or adxh<18:
        return None

    dist20=(p15-e20)/e20*100
    dist50=(p15-e50)/e50*100

    # 과도한 추격 진입 차단
    if direction=="LONG":
        if rsi>69 or rsih>72:
            return None
        if dist20>1.8 or dist50>3.0:
            return None
    else:
        if rsi<31 or rsih<28:
            return None
        if dist20<-1.8 or dist50<-3.0:
            return None

    score=0
    reasons=[]

    # 1H 구조
    score+=22
    reasons.append("1시간 추세 정렬")

    # 15M 구조
    score+=18
    reasons.append("15분 추세 정렬")

    # RSI
    if direction=="LONG":
        if 52<=rsi<=64:
            score+=12
            reasons.append("15분 RSI 상승 여력 확보")
        elif 48<=rsi<52:
            score+=7
            reasons.append("15분 RSI 중립 상단")
        else:
            score+=3

        if 50<=rsih<=68:
            score+=8
            reasons.append("1시간 RSI 상승 구간")
        elif rsih>=50:
            score+=4

        if ch15>=0.35:
            score+=8
            reasons.append("15분 상승 모멘텀")
        elif ch15>=0.10:
            score+=4

        if ch60>=0.25:
            score+=7
            reasons.append("1시간 상승 모멘텀")
        elif ch60>=0:
            score+=3
    else:
        if 36<=rsi<=48:
            score+=12
            reasons.append("15분 RSI 하락 여력 확보")
        elif 48<rsi<=52:
            score+=7
            reasons.append("15분 RSI 중립 하단")
        else:
            score+=3

        if 32<=rsih<=50:
            score+=8
            reasons.append("1시간 RSI 하락 구간")
        elif rsih<=50:
            score+=4

        if ch15<=-0.35:
            score+=8
            reasons.append("15분 하락 모멘텀")
        elif ch15<=-0.10:
            score+=4

        if ch60<=-0.25:
            score+=7
            reasons.append("1시간 하락 모멘텀")
        elif ch60<=0:
            score+=3

    # ADX
    if adx>=28:
        score+=8
        reasons.append("15분 추세 강도 우수")
    elif adx>=24:
        score+=5
    else:
        score+=2

    if adxh>=25:
        score+=7
        reasons.append("1시간 추세 강도 우수")
    elif adxh>=20:
        score+=4

    # EMA 간격
    spread15=abs(e20-e50)/p15*100
    spreadh=abs(e20h-e50h)/p60*100

    if spread15>=0.20:
        score+=4
        reasons.append("15분 EMA 구조 양호")
    elif spread15>=0.08:
        score+=2

    if spreadh>=0.25:
        score+=4
        reasons.append("1시간 EMA 구조 양호")
    elif spreadh>=0.10:
        score+=2

    # 거래량은 절대값보다 현재 유동성 최소조건만 사용
    if v15>100000 and v60>100000:
        score+=2
        reasons.append("BTCC 유동성 확인")

    # 진입 타이밍
    if direction=="LONG":
        pullback=abs(dist20)<=0.65 and rsi>=48 and ch15>=0
        momentum=dist20>0 and dist20<=1.2 and ch15>=0.35 and adx>=25
    else:
        pullback=abs(dist20)<=0.65 and rsi<=52 and ch15<=0
        momentum=dist20<0 and dist20>=-1.2 and ch15<=-0.35 and adx>=25

    setup=""
    if pullback:
        score+=9
        setup="눌림 후 재진입"
        reasons.append("EMA20 눌림 구간에서 방향 재개")
    elif momentum:
        score+=7
        setup="모멘텀 돌파"
        reasons.append("강한 단기 모멘텀 확인")
    else:
        return None

    # 점수 상한은 실제 조건에 따라 자연스럽게 결정
    if score<MIN_SCORE:
        return None

    # 너무 비슷한 고득점 신호가 반복되지 않도록 강도별 차등
    if score>=95 and not (adx>=28 and adxh>=25):
        score=94

    risk=max(atr*1.15,p15*0.006)

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
        "direction":direction,
        "score":min(int(score),100),
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
        "lev":lev,
        "setup":setup,
        "reasons":reasons
    }

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 강한 매매 시그널" if s["score"]>=STRONG_SCORE else "⚡ 매매 시그널"

    reason_text="\n".join(f"• {x}" for x in s["reasons"][:5])

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
        f"└ 1시간 변동 : {s['ch60']:+.2f}%\n\n"
        "🧠 시그널 근거\n"
        f"{reason_text}\n\n"
        "⚙️ 리스크 관리\n"
        f"├ 권장 레버리지 : {s['lev']}x\n"
        "├ TP1 도달 → SL을 진입가로 이동\n"
        "└ TP2 도달 → 추적 종료\n\n"
        f"🔗 BTCC:{s['symbol']}.P\n\n"
        "⚠️ 자동주문 없음\n"
    )

def position_msg(p,kind):
    if kind=="TP1":
        return (
            f"🎯 TP1 도달\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{p['symbol']}\n"
            f"📌 방향 : {'롱 (LONG)' if p['direction']=='LONG' else '숏 (SHORT)'}\n"
            f"💰 진입가 : {fmt(p['entry'])}\n"
            f"🎯 TP1 : {fmt(p['tp1'])}\n\n"
            "🔒 리스크 관리\n"
            "손절가 → 진입가로 이동\n"
            "이제 본절 이하 손실을 차단합니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    if kind=="TP2":
        return (
            f"🎯 TP2 도달\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 #{p['symbol']}\n"
            f"📌 방향 : {'롱 (LONG)' if p['direction']=='LONG' else '숏 (SHORT)'}\n"
            f"💰 진입가 : {fmt(p['entry'])}\n"
            f"🎯 TP2 : {fmt(p['tp2'])}\n\n"
            "✅ 목표가 달성\n"
            "포지션 추적을 종료합니다.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        f"🛑 손절가 도달\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 #{p['symbol']}\n"
        f"📌 방향 : {'롱 (LONG)' if p['direction']=='LONG' else '숏 (SHORT)'}\n"
        f"💰 진입가 : {fmt(p['entry'])}\n"
        f"🛑 손절가 : {fmt(p['sl'])}\n\n"
        "포지션 추적을 종료합니다.\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

def check_positions(state,rs):
    by={symbol(r):r for r in rs}
    remove=[]

    for sym,p in list(state["positions"].items()):
        r=by.get(sym)
        if not r:
            continue

        price=val(r,0)
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
    print(" BTCC REAL FUTURES QUANT BOT")
    print("====================================")
    print("KST:",now().isoformat())

    if not TOKEN or not CHAT_ID:
        print("TELEGRAM SECRET ERROR")
        return

    rs=rows()
    print("BTCC REAL ROWS:",len(rs))

    if not rs:
        tg("⚠️ BTCC 데이터 조회 실패\n\nTradingView BTCC 선물 데이터가 응답하지 않았습니다.")
        return

    state=load()
    check_positions(state,rs)

    candidates=[]
    for r in rs:
        try:
            s=analyze(r)
            if s:
                candidates.append(s)
        except Exception as e:
            print("ANALYZE ERROR:",e)

    candidates.sort(key=lambda x:x["score"],reverse=True)

    print("QUALIFIED:",len(candidates),"ACTIVE:",len(state["positions"]))

    sent=0
    now_ts=time.time()

    for s in candidates:
        if sent>=MAX_ALERTS:
            break

        sym=s["symbol"]

        # 동일 종목 활성 포지션 중복 방지
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

    print("NEW SIGNALS:",sent)
    print("ACTIVE:",len(state["positions"]))
    print("DONE")

if __name__=="__main__":
    main()
