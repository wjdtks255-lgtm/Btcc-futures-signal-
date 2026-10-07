import os,json,time,requests
from datetime import datetime,timezone

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()
STATE_FILE="bot_state.json"

URL="https://scanner.tradingview.com/crypto/scan"
MIN_SCORE=68
STRONG_SCORE=80
COOLDOWN=180
MAX_SYMBOLS=1000
MIN_VOLUME=100000

S=requests.Session()
S.headers.update({
    "User-Agent":"Mozilla/5.0",
    "Accept":"application/json",
    "Content-Type":"application/json",
    "Origin":"https://www.tradingview.com",
    "Referer":"https://www.tradingview.com/"
})

def tg(msg):
    if not TOKEN or not CHAT_ID:
        print("Telegram Secret missing")
        return False
    try:
        r=S.post(
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

def n(v):
    try:
        return float(v)
    except:
        return None

def fetch_btcc():
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
            {"left":"exchange","operation":"equal","right":"BTCC"}
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
        r=S.post(URL,json=payload,timeout=20)
        print("TradingView:",r.status_code)

        if r.status_code!=200:
            print(r.text[:1000])
            return [],cols

        j=r.json()
        rows=j.get("data",[])
        print("TradingView BTCC rows:",len(rows))

        result=[]

        for row in rows:
            try:
                d=dict(zip(cols,row["d"]))
                ticker=row.get("s","")

                if not ticker.startswith("BTCC:"):
                    continue

                symbol=ticker.split(":",1)[1]
                symbol=symbol.replace(".P","")

                d["symbol"]=symbol
                result.append(d)
            except:
                continue

        print("BTCC symbols:",len(result))
        return result,cols

    except Exception as e:
        print("BTCC data error:",e)
        return [],cols

def analyze(x):
    p=n(x.get("close|15"))
    e20=n(x.get("EMA20|15"))
    e50=n(x.get("EMA50|15"))
    e100=n(x.get("EMA100|15"))
    rsi=n(x.get("RSI|15"))
    adx=n(x.get("ADX|15"))
    atr=n(x.get("ATR|15"))

    hp=n(x.get("close|60"))
    he20=n(x.get("EMA20|60"))
    he50=n(x.get("EMA50|60"))
    he100=n(x.get("EMA100|60"))
    hrsi=n(x.get("RSI|60"))
    hadx=n(x.get("ADX|60"))

    c15=n(x.get("change|15")) or 0
    c60=n(x.get("change|60")) or 0
    vol=n(x.get("volume|15")) or 0

    vals=[p,e20,e50,e100,rsi,adx,atr,hp,he20,he50,he100,hrsi,hadx]

    if any(v is None for v in vals):
        return None

    if p<=0 or atr<=0:
        return None

    L=SCORE_L=0
    reasons_l=[]
    reasons_s=[]

    if he20>he50:
        L+=18
        reasons_l.append("1H EMA20 > EMA50")
    elif he20<he50:
        SCORE_L=18
        reasons_s.append("1H EMA20 < EMA50")

    if hp>he100:
        L+=10
        reasons_l.append("1H EMA100 위")
    elif hp<he100:
        SCORE_L+=10
        reasons_s.append("1H EMA100 아래")

    if p>e20>e50:
        L+=18
        reasons_l.append("15M EMA 정배열")
    elif p<e20<e50:
        SCORE_L+=18
        reasons_s.append("15M EMA 역배열")

    if p>e100:
        L+=7
        reasons_l.append("15M EMA100 위")
    elif p<e100:
        SCORE_L+=7
        reasons_s.append("15M EMA100 아래")

    if 52<rsi<72:
        L+=10
        reasons_l.append(f"RSI {rsi:.1f} 상승권")
    elif 28<rsi<48:
        SCORE_L+=10
        reasons_s.append(f"RSI {rsi:.1f} 하락권")

    if 45<hrsi<70 and he20>he50:
        L+=5
        reasons_l.append(f"1H RSI {hrsi:.1f}")
    elif 30<hrsi<55 and he20<he50:
        SCORE_L+=5
        reasons_s.append(f"1H RSI {hrsi:.1f}")

    if adx>=18:
        if L>SCORE_L:
            L+=7
            reasons_l.append(f"ADX {adx:.1f} 추세 확인")
        elif SCORE_L>L:
            SCORE_L+=7
            reasons_s.append(f"ADX {adx:.1f} 추세 확인")

    if hadx>=18:
        if L>SCORE_L:
            L+=5
            reasons_l.append(f"1H ADX {hadx:.1f}")
        elif SCORE_L>L:
            SCORE_L+=5
            reasons_s.append(f"1H ADX {hadx:.1f}")

    if c15>0.35:
        L+=8
        reasons_l.append(f"15M 모멘텀 +{c15:.2f}%")
    elif c15<-0.35:
        SCORE_L+=8
        reasons_s.append(f"15M 모멘텀 {c15:.2f}%")

    if c60>0.5:
        L+=5
        reasons_l.append(f"1H 변화 +{c60:.2f}%")
    elif c60<-0.5:
        SCORE_L+=5
        reasons_s.append(f"1H 변화 {c60:.2f}%")

    if vol>=MIN_VOLUME:
        if L>SCORE_L and c15>0:
            L+=7
            reasons_l.append("15M 거래량 확인")
        elif SCORE_L>L and c15<0:
            SCORE_L+=7
            reasons_s.append("15M 거래량 확인")

    if L>=SCORE_L and L>=MIN_SCORE:
        return {
            "direction":"LONG",
            "score":L,
            "price":p,
            "atr":atr,
            "rsi":rsi,
            "adx":adx,
            "c15":c15,
            "c60":c60,
            "reasons":reasons_l
        }

    if SCORE_L>L and SCORE_L>=MIN_SCORE:
        return {
            "direction":"SHORT",
            "score":SCORE_L,
            "price":p,
            "atr":atr,
            "rsi":rsi,
            "adx":adx,
            "c15":c15,
            "c60":c60,
            "reasons":reasons_s
        }

    return None

def levels(price,atr,d):
    risk=max(atr*1.25,price*0.008)

    if d=="LONG":
        return price-risk,price+risk*1.5,price+risk*2.5,risk

    return price+risk,price-risk*1.5,price-risk*2.5,risk

def lev(price,atr):
    x=atr/price*100
    if x>=3:return 3
    if x>=2:return 5
    if x>=1:return 8
    return 10

def fmt(x):
    if x>=100:return f"{x:,.2f}"
    if x>=1:return f"{x:,.4f}"
    if x>=0.01:return f"{x:,.6f}"
    return f"{x:.8f}"

def cooldown_ok(state,sym,d):
    key=f"{sym}:{d}"
    return time.time()-state["signals"].get(key,0)>=COOLDOWN*60

def track(state,data):
    remove=[]

    for sym,p in state["positions"].items():
        x=data.get(sym)
        if not x:
            continue

        price=n(x.get("close|15"))
        if price is None:
            continue

        d=p["direction"]
        sl=p["sl"]
        tp1=p["tp1"]
        tp2=p["tp2"]

        if d=="LONG":
            if not p.get("tp1_hit") and price>=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]

                tg(
                    f"🎯 <b>BTCC TP1 HIT</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 LONG\n"
                    f"💰 {fmt(price)}\n"
                    f"🎯 TP1 {fmt(tp1)}\n"
                    f"🔒 SL → ENTRY"
                )

            elif price>=tp2:
                tg(
                    f"🏆 <b>BTCC TP2 HIT</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 LONG 종료\n"
                    f"💰 {fmt(price)}\n"
                    f"🎯 TP2 {fmt(tp2)}"
                )
                remove.append(sym)

            elif price<=sl:
                tg(
                    f"🛑 <b>BTCC STOP LOSS</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 LONG 종료\n"
                    f"💰 {fmt(price)}\n"
                    f"🛑 SL {fmt(sl)}"
                )
                remove.append(sym)

        else:
            if not p.get("tp1_hit") and price<=tp1:
                p["tp1_hit"]=True
                p["sl"]=p["entry"]

                tg(
                    f"🎯 <b>BTCC TP1 HIT</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 SHORT\n"
                    f"💰 {fmt(price)}\n"
                    f"🎯 TP1 {fmt(tp1)}\n"
                    f"🔒 SL → ENTRY"
                )

            elif price<=tp2:
                tg(
                    f"🏆 <b>BTCC TP2 HIT</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📉 SHORT 종료\n"
                    f"💰 {fmt(price)}\n"
                    f"🎯 TP2 {fmt(tp2)}"
                )
                remove.append(sym)

            elif price>=sl:
                tg(
                    f"🛑 <b>BTCC STOP LOSS</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"#{sym}\n"
                    f"📈 SHORT 종료\n"
                    f"💰 {fmt(price)}\n"
                    f"🛑 SL {fmt(sl)}"
                )
                remove.append(sym)

    for sym in remove:
        state["positions"].pop(sym,None)

def message(sym,x,sl,tp1,tp2,leverage):
    icon="🟢" if x["direction"]=="LONG" else "🔴"
    level="🔥 STRONG" if x["score"]>=STRONG_SCORE else "⚡ SIGNAL"
    reasons="\n".join("• "+r for r in x["reasons"][:7])

    return (
        f"{icon} <b>BTCC FUTURES {level}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"#{sym}\n"
        f"{'📈 LONG' if x['direction']=='LONG' else '📉 SHORT'}\n\n"
        f"💰 ENTRY  <b>{fmt(x['price'])}</b>\n"
        f"🛑 SL     <b>{fmt(sl)}</b>\n"
        f"🎯 TP1    <b>{fmt(tp1)}</b>\n"
        f"🎯 TP2    <b>{fmt(tp2)}</b>\n"
        f"⚡ LEV    <b>{leverage}x</b>\n\n"
        f"📊 SCORE  <b>{x['score']}</b>\n"
        f"RSI {x['rsi']:.1f} | ADX {x['adx']:.1f}\n"
        f"15M {x['c15']:+.2f}% | 1H {x['c60']:+.2f}%\n\n"
        f"📌 <b>진입 근거</b>\n{reasons}\n\n"
        f"🏦 DATA: <b>BTCC Futures</b>\n"
        f"📊 Feed: TradingView BTCC\n"
        f"⚠️ 참고용 시그널"
    )

def main():
    print("="*55)
    print("🚀 BTCC FUTURES QUANT SCANNER V9.0")
    print("DATA: BTCC / TradingView")
    print("="*55)

    if not TOKEN or not CHAT_ID:
        print("❌ Telegram Secrets 없음")
        return

    state=load_state()

    rows,_=fetch_btcc()

    if not rows:
        tg(
            "❌ <b>BTCC 시장 데이터 오류</b>\n\n"
            "TradingView BTCC Feed에서 데이터를 가져오지 못했습니다."
        )
        return

    data={x["symbol"]:x for x in rows if x.get("symbol")}

    print("BTCC symbols:",len(data))

    track(state,data)

    candidates=[]

    for sym,x in data.items():
        if sym in state["positions"]:
            continue

        try:
            a=analyze(x)

            if not a:
                continue

            if not cooldown_ok(state,sym,a["direction"]):
                continue

            candidates.append((sym,a))

            print(
                f"{sym:18} "
                f"{a['direction']:5} "
                f"score={a['score']:3}"
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

        leverage=lev(x["price"],x["atr"])

        if tg(message(sym,x,sl,tp1,tp2,leverage)):
            state["positions"][sym]={
                "direction":x["direction"],
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
                f"{sym}:{x['direction']}"
            ]=time.time()

            sent+=1

    save(state)

    print("="*55)
    print("SCAN COMPLETE")
    print("BTCC:",len(data))
    print("Candidates:",len(candidates))
    print("Signals:",sent)
    print("Active:",len(state["positions"]))
    print("="*55)

    tg(
        f"📡 <b>BTCC SCAN COMPLETE</b>\n\n"
        f"🏦 BTCC 종목: <b>{len(data)}</b>\n"
        f"🎯 후보: <b>{len(candidates)}</b>\n"
        f"🚨 신규: <b>{sent}</b>\n"
        f"📌 ACTIVE: <b>{len(state['positions'])}</b>"
    )

if __name__=="__main__":
    main()
