import os,json,time,requests,pandas as pd
from datetime import datetime,timezone

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()
STATE_FILE="bot_state.json"

TV="https://scanner.tradingview.com/crypto/scan"
MIN_SCORE=68
STRONG_SCORE=80
COOLDOWN=180
MIN_VOLUME=100000
MAX_SYMBOLS=1000

H=requests.Session()
H.headers.update({
    "User-Agent":"Mozilla/5.0",
    "Content-Type":"application/json",
    "Origin":"https://www.tradingview.com",
    "Referer":"https://www.tradingview.com/"
})

def tg(msg):
    if not TOKEN or not CHAT_ID:
        print("Telegram Secret 없음")
        return False
    try:
        r=H.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id":CHAT_ID,
                "text":msg,
                "parse_mode":"HTML",
                "disable_web_page_preview":True
            },
            timeout=15
        )
        print("Telegram:",r.status_code)
        return r.ok
    except Exception as e:
        print("Telegram error:",e)
        return False

def load():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            s=json.load(f)
        s.setdefault("positions",{})
        s.setdefault("signals",{})
        return s
    except:
        return {"positions":{},"signals":{}}

def save(s):
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump(s,f,ensure_ascii=False,indent=2)

def tv_scan():
    cols=[
        "name","description","close","change","volume",
        "close|15","volume|15","EMA20|15","EMA50|15",
        "EMA100|15","RSI|15","ADX|15","ATR|15",
        "close|60","volume|60","EMA20|60","EMA50|60",
        "EMA100|60","RSI|60","ADX|60","ATR|60",
        "change|15","change|60"
    ]

    payload={
        "filter":[
            {"left":"exchange","operation":"equal","right":"BTCC"},
            {"left":"type","operation":"equal","right":"crypto"},
            {"left":"volume|15","operation":"nempty"}
        ],
        "options":{
            "lang":"en",
            "active_symbols_only":True
        },
        "symbols":{
            "query":{"types":[]},
            "tickers":[]
        },
        "columns":cols,
        "sort":{
            "sortBy":"volume|15",
            "sortOrder":"desc"
        },
        "range":[0,MAX_SYMBOLS]
    }

    try:
        r=H.post(TV,json=payload,timeout=20)
        print("BTCC TradingView:",r.status_code)

        if r.status_code!=200:
            print(r.text[:500])
            return []

        j=r.json()
        data=j.get("data",[])
        print("BTCC total:",j.get("totalCount",len(data)))
        print("BTCC returned:",len(data))

        out=[]
        for x in data:
            try:
                d=dict(zip(cols,x["d"]))
                d["ticker"]=x["s"]
                out.append(d)
            except:
                pass
        return out

    except Exception as e:
        print("BTCC data error:",e)
        return []

def num(x):
    try:
        return float(x)
    except:
        return None

def analyze(x):
    p=x

    price=num(p.get("close|15"))
    ema20=num(p.get("EMA20|15"))
    ema50=num(p.get("EMA50|15"))
    ema100=num(p.get("EMA100|15"))
    rsi=num(p.get("RSI|15"))
    adx=num(p.get("ADX|15"))
    atr=num(p.get("ATR|15"))
    vol=num(p.get("volume|15"))

    hprice=num(p.get("close|60"))
    hema20=num(p.get("EMA20|60"))
    hema50=num(p.get("EMA50|60"))
    hema100=num(p.get("EMA100|60"))
    hrsi=num(p.get("RSI|60"))
    hadx=num(p.get("ADX|60"))

    ch15=num(p.get("change|15")) or 0
    ch60=num(p.get("change|60")) or 0

    if None in [price,ema20,ema50,ema100,rsi,adx,atr,
                hprice,hema20,hema50,hema100,hrsi,hadx]:
        return None

    if price<=0 or atr<=0:
        return None

    L=0
    S=0
    lr=[]
    sr=[]

    # 1H trend
    if hema20>hema50:
        L+=18
        lr.append("1H EMA20 > EMA50 상승 추세")
    elif hema20<hema50:
        S+=18
        sr.append("1H EMA20 < EMA50 하락 추세")

    if hprice>hema100:
        L+=10
        lr.append("1H EMA100 위")
    elif hprice<hema100:
        S+=10
        sr.append("1H EMA100 아래")

    # 15M structure
    if price>ema20>ema50:
        L+=18
        lr.append("15M EMA 정배열")
    elif price<ema20<ema50:
        S+=18
        sr.append("15M EMA 역배열")

    if price>ema100:
        L+=7
        lr.append("15M EMA100 위")
    elif price<ema100:
        S+=7
        sr.append("15M EMA100 아래")

    # RSI
    if 52<rsi<72:
        L+=10
        lr.append(f"15M RSI {rsi:.1f} 상승권")
    elif 28<rsi<48:
        S+=10
        sr.append(f"15M RSI {rsi:.1f} 하락권")

    if 45<hrsi<70 and hema20>hema50:
        L+=5
        lr.append(f"1H RSI {hrsi:.1f}")
    elif 30<hrsi<55 and hema20<hema50:
        S+=5
        sr.append(f"1H RSI {hrsi:.1f}")

    # ADX
    if adx>=18:
        if L>S:
            L+=7
            lr.append(f"ADX {adx:.1f} 추세 확인")
        elif S>L:
            S+=7
            sr.append(f"ADX {adx:.1f} 추세 확인")

    if hadx>=18:
        if L>S:
            L+=5
            lr.append(f"1H ADX {hadx:.1f}")
        elif S>L:
            S+=5
            sr.append(f"1H ADX {hadx:.1f}")

    # Momentum
    if ch15>0.35:
        L+=8
        lr.append(f"15M 모멘텀 +{ch15:.2f}%")
    elif ch15<-0.35:
        S+=8
        sr.append(f"15M 모멘텀 {ch15:.2f}%")

    if ch60>0.5:
        L+=5
        lr.append(f"1H 변화 +{ch60:.2f}%")
    elif ch60<-0.5:
        S+=5
        sr.append(f"1H 변화 {ch60:.2f}%")

    # Volume
    if vol and vol>=MIN_VOLUME:
        if L>S and ch15>0:
            L+=7
            lr.append("15M 거래량 충분")
        elif S>L and ch15<0:
            S+=7
            sr.append("15M 거래량 충분")

    if L>=S and L>=MIN_SCORE:
        return {
            "direction":"LONG",
            "score":L,
            "price":price,
            "atr":atr,
            "rsi":rsi,
            "adx":adx,
            "change15":ch15,
            "change60":ch60,
            "reasons":lr
        }

    if S>L and S>=MIN_SCORE:
        return {
            "direction":"SHORT",
            "score":S,
            "price":price,
            "atr":atr,
            "rsi":rsi,
            "adx":adx,
            "change15":ch15,
            "change60":ch60,
            "reasons":sr
        }

    return None

def levels(price,atr,d):
    risk=max(atr*1.25,price*0.008)

    if d=="LONG":
        sl=price-risk
        tp1=price+risk*1.5
        tp2=price+risk*2.5
    else:
        sl=price+risk
        tp1=price-risk*1.5
        tp2=price-risk*2.5

    return sl,tp1,tp2,risk

def leverage(price,atr):
    v=atr/price*100
    if v>=3:return 3
    if v>=2:return 5
    if v>=1:return 8
    return 10

def fmt(v):
    if v>=100:return f"{v:,.2f}"
    if v>=1:return f"{v:,.4f}"
    if v>=0.01:return f"{v:,.6f}"
    return f"{v:.8f}"

def cooldown(s,t,d):
    k=f"{t}:{d}"
    last=s["signals"].get(k,0)
    return time.time()-last>=COOLDOWN*60

def track(s,data):
    remove=[]

    for sym,p in s["positions"].items():
        x=data.get(sym)
        if not x:
            continue

        q=num(x.get("close|15"))
        if q is None:
            continue

        d=p["direction"]
        sl=p["sl"]
        tp1=p["tp1"]
        tp2=p["tp2"]

        if d=="LONG":
            if not p.get("tp1_hit") and q>=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]

                tg(
                    f"🎯 <b>BTCC TP1 HIT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 LONG\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP1: <b>{fmt(tp1)}</b>\n"
                    f"🔒 SL → ENTRY\n"
                    f"✅ 1차 익절 도달"
                )

            elif q>=tp2:
                tg(
                    f"🏆 <b>BTCC TP2 HIT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 LONG 종료\n"
                    f"💰 청산가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP2: <b>{fmt(tp2)}</b>\n"
                    f"🔥 포지션 종료"
                )
                remove.append(sym)

            elif q<=sl:
                tg(
                    f"🛑 <b>BTCC STOP LOSS</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 LONG 종료\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🛑 SL: <b>{fmt(sl)}</b>"
                )
                remove.append(sym)

        else:
            if not p.get("tp1_hit") and q<=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]

                tg(
                    f"🎯 <b>BTCC TP1 HIT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 SHORT\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP1: <b>{fmt(tp1)}</b>\n"
                    f"🔒 SL → ENTRY\n"
                    f"✅ 1차 익절 도달"
                )

            elif q<=tp2:
                tg(
                    f"🏆 <b>BTCC TP2 HIT</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 SHORT 종료\n"
                    f"💰 청산가: <b>{fmt(q)}</b>\n"
                    f"🎯 TP2: <b>{fmt(tp2)}</b>\n"
                    f"🔥 포지션 종료"
                )
                remove.append(sym)

            elif q>=sl:
                tg(
                    f"🛑 <b>BTCC STOP LOSS</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 SHORT 종료\n"
                    f"💰 현재가: <b>{fmt(q)}</b>\n"
                    f"🛑 SL: <b>{fmt(sl)}</b>"
                )
                remove.append(sym)

    for x in remove:
        s["positions"].pop(x,None)

def signal(sym,x,sl,tp1,tp2,lev):
    icon="🟢" if x["direction"]=="LONG" else "🔴"
    strength="🔥 STRONG" if x["score"]>=STRONG_SCORE else "⚡ SIGNAL"

    reasons="\n".join(
        f"• {r}" for r in x["reasons"][:7]
    )

    return (
        f"{icon} <b>BTCC FUTURES {strength}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"#{sym}\n"
        f"{'📈 LONG' if x['direction']=='LONG' else '📉 SHORT'}\n\n"
        f"💰 ENTRY  <b>{fmt(x['price'])}</b>\n"
        f"🛑 SL     <b>{fmt(sl)}</b>\n"
        f"🎯 TP1    <b>{fmt(tp1)}</b>\n"
        f"🎯 TP2    <b>{fmt(tp2)}</b>\n"
        f"⚡ LEV    <b>{lev}x</b>\n\n"
        f"📊 SCORE  <b>{x['score']}</b>\n"
        f"RSI      {x['rsi']:.1f}\n"
        f"ADX      {x['adx']:.1f}\n"
        f"15M      {x['change15']:+.2f}%\n"
        f"1H       {x['change60']:+.2f}%\n\n"
        f"📌 <b>진입 근거</b>\n"
        f"{reasons}\n\n"
        f"🏦 DATA <b>BTCC Futures</b>\n"
        f"📊 Feed: TradingView BTCC\n"
        f"⚠️ 참고용 시그널 / 레버리지 주의"
    )

def main():
    print("="*58)
    print("🚀 BTCC FUTURES QUANT SCANNER V8.0")
    print("DATA: BTCC via TradingView")
    print("="*58)

    if not TOKEN or not CHAT_ID:
        print("❌ Telegram Secrets 없음")
        return

    state=load()

    rows=tv_scan()

    if not rows:
        tg(
            "❌ <b>BTCC 시장 데이터 오류</b>\n\n"
            "BTCC TradingView Market Feed에서 데이터를 가져오지 못했습니다."
        )
        return

    data={}
    for x in rows:
        t=x.get("ticker","")
        if t.startswith("BTCC:"):
            sym=t.split(":",1)[1]
            sym=sym.replace(".P","")
            data[sym]=x

    print("BTCC 종목:",len(data))

    track(state,data)
    save(state)

    candidates=[]

    for sym,x in data.items():
        try:
            if sym in state["positions"]:
                continue

            if not x.get("close|15"):
                continue

            a=analyze(x)

            if not a:
                continue

            if not cooldown(state,sym,a["direction"]):
                continue

            candidates.append((sym,a))

            print(
                f"{sym:18} "
                f"{a['direction']:5} "
                f"score={a['score']:3} "
                f"price={fmt(a['price'])}"
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
            x["direction"]
        )

        lev=leverage(x["price"],x["atr"])

        if tg(signal(sym,x,sl,tp1,tp2,lev)):
            state["positions"][sym]={
                "direction":x["direction"],
                "entry":x["price"],
                "sl":sl,
                "tp1":tp1,
                "tp2":tp2,
                "tp1_hit":False,
                "score":x["score"],
                "leverage":lev,
                "created":datetime.now(timezone.utc).isoformat()
            }

            state["signals"][
                f"{sym}:{x['direction']}"
            ]=time.time()

            sent+=1

    save(state)

    print("="*58)
    print("SCAN COMPLETE")
    print("BTCC symbols :",len(data))
    print("Candidates   :",len(candidates))
    print("New signals  :",sent)
    print("Active       :",len(state["positions"]))
    print("="*58)

    tg(
        f"📡 <b>BTCC SCAN COMPLETE</b>\n\n"
        f"🏦 BTCC 종목: <b>{len(data)}</b>\n"
        f"🎯 후보: <b>{len(candidates)}</b>\n"
        f"🚨 신규신호: <b>{sent}</b>\n"
        f"📌 ACTIVE: <b>{len(state['positions'])}</b>\n\n"
        f"{'🔥 강한 진입 후보가 발견되었습니다.' if sent else '⏳ 현재 조건을 만족하는 신규 진입 없음'}"
    )

if __name__=="__main__":
    main()
