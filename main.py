import os,json,time,requests,pandas as pd
from datetime import datetime,timezone

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()
STATE_FILE="bot_state.json"

BASE="https://api.bybit.com"
MIN_SCORE=68
STRONG_SCORE=80
COOLDOWN=180
MAX_SCAN=120
MIN_VALUE=1_000_000
TIMEOUT=12

S=requests.Session()
S.headers.update({"User-Agent":"BTCC-Signal-Scanner/7.0","Accept":"application/json"})

def tg(msg):
    if not TOKEN or not CHAT_ID:
        print("❌ Telegram Secret 없음")
        return False
    try:
        r=S.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"},
            timeout=15
        )
        print("Telegram:",r.status_code)
        return r.ok
    except Exception as e:
        print("Telegram error:",e)
        return False

def api(path,params=None,retry=2):
    for n in range(retry+1):
        try:
            r=S.get(BASE+path,params=params,timeout=TIMEOUT)
            if r.status_code!=200:
                print("API",path,"HTTP",r.status_code)
                if n<retry:
                    time.sleep(1)
                    continue
                return None
            j=r.json()
            if j.get("retCode")!=0:
                print("API error:",j.get("retMsg"))
                return None
            return j.get("result",{})
        except Exception as e:
            print("API error:",e)
            if n<retry:
                time.sleep(1)
    return None

def load_state():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            x=json.load(f)
        x.setdefault("positions",{})
        x.setdefault("signals",{})
        return x
    except:
        return {"positions":{},"signals":{}}

def save_state(x):
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump(x,f,ensure_ascii=False,indent=2)

def symbols():
    out=[]
    cursor=""
    while True:
        p={"category":"linear","limit":1000}
        if cursor:p["cursor"]=cursor
        j=api("/v5/market/instruments-info",p)
        if not j:break
        for x in j.get("list",[]):
            if x.get("status")!="Trading":continue
            if x.get("quoteCoin")!="USDT":continue
            if x.get("contractType")!="LinearPerpetual":continue
            sym=x["symbol"]
            if sym.endswith("USDT"):
                out.append(sym)
        cursor=j.get("nextPageCursor","")
        if not cursor:break
    return list(dict.fromkeys(out))

def ticker_map():
    j=api("/v5/market/tickers",{"category":"linear"})
    d={}
    if not j:return d
    for x in j.get("list",[]):
        try:
            if x.get("symbol","").endswith("USDT"):
                d[x["symbol"]]={
                    "price":float(x["lastPrice"]),
                    "value":float(x.get("turnover24h") or 0),
                    "change":float(x.get("price24hPcnt") or 0)*100
                }
        except:
            pass
    return d

def candles(sym,interval,limit=180):
    j=api("/v5/market/kline",{
        "category":"linear",
        "symbol":sym,
        "interval":interval,
        "limit":limit
    })
    if not j:return None
    rows=j.get("list",[])
    if len(rows)<80:return None
    rows=rows[::-1]
    df=pd.DataFrame(rows,columns=["time","open","high","low","close","volume","turnover"])
    for c in ["open","high","low","close","volume","turnover"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    return df.dropna().reset_index(drop=True)

def calc(df):
    c=df["close"]
    h=df["high"]
    l=df["low"]
    v=df["volume"]

    df["ema20"]=c.ewm(span=20,adjust=False).mean()
    df["ema50"]=c.ewm(span=50,adjust=False).mean()
    df["ema100"]=c.ewm(span=100,adjust=False).mean()

    d=c.diff()
    gain=d.clip(lower=0)
    loss=-d.clip(upper=0)
    ag=gain.ewm(alpha=1/14,adjust=False).mean()
    al=loss.ewm(alpha=1/14,adjust=False).mean()
    rs=ag/al.replace(0,float("nan"))
    df["rsi"]=100-(100/(1+rs))

    tr=pd.concat([
        h-l,
        (h-c.shift()).abs(),
        (l-c.shift()).abs()
    ],axis=1).max(axis=1)
    df["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()

    plus=(h.diff()).clip(lower=0)
    minus=(-l.diff()).clip(lower=0)
    plus[plus<minus]=0
    minus[minus<plus]=0
    atr=tr.ewm(alpha=1/14,adjust=False).mean()
    pdi=100*plus.ewm(alpha=1/14,adjust=False).mean()/atr
    mdi=100*minus.ewm(alpha=1/14,adjust=False).mean()/atr
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,float("nan"))
    df["adx"]=dx.ewm(alpha=1/14,adjust=False).mean()

    df["vma"]=v.rolling(20).mean()
    df["mom4"]=c.pct_change(4)*100
    return df

def analyze(h1,m15):
    a=calc(h1.copy())
    b=calc(m15.copy())

    x=a.iloc[-1]
    px=b.iloc[-1]
    p1=b.iloc[-2]

    scoreL=0
    scoreS=0
    rl=[]
    rs=[]

    if x.ema20>x.ema50:
        scoreL+=18
        rl.append("1H EMA20 > EMA50 상승추세")
    elif x.ema20<x.ema50:
        scoreS+=18
        rs.append("1H EMA20 < EMA50 하락추세")

    if x.close>x.ema100:
        scoreL+=10
        rl.append("1H EMA100 위")
    elif x.close<x.ema100:
        scoreS+=10
        rs.append("1H EMA100 아래")

    if px.close>px.ema20>px.ema50:
        scoreL+=18
        rl.append("15M EMA 정배열")
    elif px.close<px.ema20<px.ema50:
        scoreS+=18
        rs.append("15M EMA 역배열")

    if px.rsi>52 and px.rsi<72 and px.rsi>p1.rsi:
        scoreL+=12
        rl.append(f"RSI 상승 {px.rsi:.1f}")
    elif px.rsi<48 and px.rsi>28 and px.rsi<p1.rsi:
        scoreS+=12
        rs.append(f"RSI 하락 {px.rsi:.1f}")

    if px.rsi<38 and px.rsi>p1.rsi:
        scoreL+=8
        rl.append("RSI 과매도 반등")
    if px.rsi>62 and px.rsi<p1.rsi:
        scoreS+=8
        rs.append("RSI 과매수 하락")

    if px.volume>px.vma*1.15:
        if px.close>p1.close:
            scoreL+=10
            rl.append("거래량 증가 + 상승")
        elif px.close<p1.close:
            scoreS+=10
            rs.append("거래량 증가 + 하락")

    if px.mom4>0.35:
        scoreL+=10
        rl.append(f"4봉 모멘텀 +{px.mom4:.2f}%")
    elif px.mom4<-0.35:
        scoreS+=10
        rs.append(f"4봉 모멘텀 {px.mom4:.2f}%")

    if px.adx>=18:
        if scoreL>scoreS:
            scoreL+=7
            rl.append(f"ADX {px.adx:.1f} 추세확인")
        elif scoreS>scoreL:
            scoreS+=7
            rs.append(f"ADX {px.adx:.1f} 추세확인")

    if scoreL>=scoreS and scoreL>=MIN_SCORE:
        return {
            "dir":"LONG",
            "score":scoreL,
            "reasons":rl,
            "price":float(px.close),
            "atr":float(px.atr),
            "rsi":float(px.rsi),
            "adx":float(px.adx),
            "mom":float(px.mom4)
        }

    if scoreS>scoreL and scoreS>=MIN_SCORE:
        return {
            "dir":"SHORT",
            "score":scoreS,
            "reasons":rs,
            "price":float(px.close),
            "atr":float(px.atr),
            "rsi":float(px.rsi),
            "adx":float(px.adx),
            "mom":float(px.mom4)
        }

    return None

def levels(price,atr,direction):
    risk=max(atr*1.25,price*0.008)
    if direction=="LONG":
        sl=price-risk
        tp1=price+risk*1.5
        tp2=price+risk*2.5
    else:
        sl=price+risk
        tp1=price-risk*1.5
        tp2=price-risk*2.5
    return sl,tp1,tp2,risk

def lev(price,atr):
    pct=atr/price*100
    if pct>=3:return 3
    if pct>=2:return 5
    if pct>=1:return 8
    return 10

def cooldown_ok(state,sym,direction):
    k=f"{sym}:{direction}"
    t=state["signals"].get(k,0)
    return time.time()-t>=COOLDOWN*60

def fmt(p):
    if p>=100:return f"{p:,.2f}"
    if p>=1:return f"{p:,.4f}"
    return f"{p:,.6f}"

def track(state,prices):
    remove=[]
    for sym,p in state["positions"].items():
        if sym not in prices:continue
        q=prices[sym]["price"]
        d=p["direction"]
        sl=p["sl"]
        tp1=p["tp1"]
        tp2=p["tp2"]

        if d=="LONG":
            if not p.get("tp1_hit") and q>=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(
                    f"🎯 <b>TP1 HIT</b>\n\n"
                    f"#{sym}\n"
                    f"📈 LONG\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP1: <b>{fmt(tp1)}</b>\n"
                    f"🔒 SL → ENTRY\n"
                    f"✅ 1차 목표 달성"
                )
            elif q>=tp2:
                tg(
                    f"🏆 <b>TP2 HIT</b>\n\n"
                    f"#{sym}\n"
                    f"📈 LONG\n"
                    f"💰 청산가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP2: <b>{fmt(tp2)}</b>\n"
                    f"🔥 포지션 종료"
                )
                remove.append(sym)
            elif q<=sl:
                tg(
                    f"🛑 <b>STOP LOSS</b>\n\n"
                    f"#{sym}\n"
                    f"📉 LONG 종료\n"
                    f"💰 가격: <b>{fmt(q)}</b>\n"
                    f"🛑 SL: <b>{fmt(sl)}</b>"
                )
                remove.append(sym)

        else:
            if not p.get("tp1_hit") and q<=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]
                tg(
                    f"🎯 <b>TP1 HIT</b>\n\n"
                    f"#{sym}\n"
                    f"📉 SHORT\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP1: <b>{fmt(tp1)}</b>\n"
                    f"🔒 SL → ENTRY\n"
                    f"✅ 1차 목표 달성"
                )
            elif q<=tp2:
                tg(
                    f"🏆 <b>TP2 HIT</b>\n\n"
                    f"#{sym}\n"
                    f"📉 SHORT\n"
                    f"💰 청산가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP2: <b>{fmt(tp2)}</b>\n"
                    f"🔥 포지션 종료"
                )
                remove.append(sym)
            elif q>=sl:
                tg(
                    f"🛑 <b>STOP LOSS</b>\n\n"
                    f"#{sym}\n"
                    f"📈 SHORT 종료\n"
                    f"💰 가격: <b>{fmt(q)}</b>\n"
                    f"🛑 SL: <b>{fmt(sl)}</b>"
                )
                remove.append(sym)

    for sym in remove:
        state["positions"].pop(sym,None)

def signal_message(sym,x,sl,tp1,tp2,leverage):
    icon="🟢" if x["dir"]=="LONG" else "🔴"
    strength="🔥 STRONG" if x["score"]>=STRONG_SCORE else "⚡ SIGNAL"
    reasons="\n".join(f"• {r}" for r in x["reasons"][:6])

    return (
        f"{icon} <b>BTCC FUTURES {strength}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"#{sym}\n"
        f"{'📈 LONG' if x['dir']=='LONG' else '📉 SHORT'}\n\n"
        f"💰 Entry : <b>{fmt(x['price'])}</b>\n"
        f"🛑 SL : <b>{fmt(sl)}</b>\n"
        f"🎯 TP1 : <b>{fmt(tp1)}</b>\n"
        f"🎯 TP2 : <b>{fmt(tp2)}</b>\n"
        f"⚡ Leverage : <b>{leverage}x</b>\n\n"
        f"📊 Score : <b>{x['score']}</b>\n"
        f"RSI : {x['rsi']:.1f}  |  ADX : {x['adx']:.1f}\n"
        f"Momentum : {x['mom']:+.2f}%\n\n"
        f"📌 <b>진입 근거</b>\n{reasons}\n\n"
        f"⚠️ BTCC 거래용 참고 시그널\n"
        f"📍 Data: Bybit Public Futures"
    )

def main():
    print("="*52)
    print("🚀 BTCC FUTURES QUANT SCANNER V7.0")
    print("Data: Bybit Public Futures")
    print("="*52)

    if not TOKEN or not CHAT_ID:
        print("❌ Telegram Secret 확인 필요")
        return

    state=load_state()
    prices=ticker_map()

    if not prices:
        tg("❌ <b>시장 데이터 오류</b>\nBybit Public Futures API 응답 없음")
        return

    track(state,prices)
    save_state(state)

    syms=symbols()
    if not syms:
        tg("❌ <b>종목 조회 실패</b>\nBybit 선물 종목을 가져오지 못했습니다.")
        return

    liquid=[
        s for s in syms
        if s in prices and prices[s]["value"]>=MIN_VALUE
    ]

    liquid.sort(
        key=lambda s:prices[s]["value"],
        reverse=True
    )

    liquid=liquid[:MAX_SCAN]

    print("전체 선물:",len(syms))
    print("유동성 스캔:",len(liquid))
    print("ACTIVE:",len(state["positions"]))

    candidates=[]

    for i,sym in enumerate(liquid,1):
        try:
            h1=candles(sym,"60",160)
            m15=candles(sym,"15",160)
            if h1 is None or m15 is None:
                continue

            x=analyze(h1,m15)
            if not x:
                continue

            if sym in state["positions"]:
                continue

            if not cooldown_ok(state,sym,x["dir"]):
                continue

            candidates.append((sym,x))
            print(
                f"{sym:16} {x['dir']:5} "
                f"score={x['score']:3} "
                f"RSI={x['rsi']:.1f}"
            )
        except Exception as e:
            print(sym,"ERROR",e)

    candidates.sort(
        key=lambda z:z[1]["score"],
        reverse=True
    )

    sent=0

    for sym,x in candidates:
        sl,tp1,tp2,risk=levels(
            x["price"],
            x["atr"],
            x["dir"]
        )

        leverage=lev(x["price"],x["atr"])

        if tg(
            signal_message(
                sym,x,sl,tp1,tp2,leverage
            )
        ):
            state["positions"][sym]={
                "direction":x["dir"],
                "entry":x["price"],
                "sl":sl,
                "tp1":tp1,
                "tp2":tp2,
                "tp1_hit":False,
                "score":x["score"],
                "leverage":leverage,
                "created":datetime.now(timezone.utc).isoformat()
            }

            state["signals"][
                f"{sym}:{x['dir']}"
            ]=time.time()

            sent+=1

    save_state(state)

    print("="*52)
    print("SCAN COMPLETE")
    print("Candidates:",len(candidates))
    print("Sent:",sent)
    print("Active:",len(state["positions"]))
    print("="*52)

    summary=(
        f"📡 <b>BTCC Scanner 완료</b>\n\n"
        f"🔎 스캔: {len(liquid)}개\n"
        f"🎯 후보: {len(candidates)}개\n"
        f"🚨 신규신호: {sent}개\n"
        f"📌 ACTIVE: {len(state['positions'])}개"
    )

    if sent==0:
        summary+="\n\n⏳ 현재 조건을 만족하는 신규 진입 없음"

    tg(summary)

if __name__=="__main__":
    main()
