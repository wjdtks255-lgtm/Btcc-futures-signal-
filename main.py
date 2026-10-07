# main.py
import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV="https://scanner.tradingview.com/crypto/scan"
THRESHOLD=78
STRONG=88
COOLDOWN=180
MAX_ALERTS=5

COL=[
"close|15","volume|15","EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"close|60","volume|60","EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60","ATR|60",
"change|15","change|60"
]
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.tradingview.com","Referer":"https://www.tradingview.com/"}

def now():return datetime.now(KST)
def load():
    try:
        with open(STATE_FILE,encoding="utf-8") as f:s=json.load(f)
    except:s={"positions":{},"signals":{}}
    s.setdefault("positions",{});s.setdefault("signals",{})
    return s
def save(s):
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:json.dump(s,f,ensure_ascii=False,indent=2)
    os.replace(STATE_FILE+".tmp",STATE_FILE)

def tv(payload):
    try:
        r=requests.post(TV,json=payload,headers={**H,"Content-Type":"application/json"},timeout=25)
        print("TV",r.status_code)
        return r.json().get("data",[]) if r.status_code==200 else []
    except Exception as e:
        print("TV ERROR",e);return []

def get_rows():
    p={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[{"left":"exchange","operation":"equal","right":"BTCC"}],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    }
    return tv(p)

def val(r,i,d=0):
    try:
        x=r.get("d",[])[i]
        return float(x) if x is not None else d
    except:return d

def sym(r):return str(r.get("s","")).split(":",1)[-1].replace(".P","")

def analyze(r):
    p15,v15,e20,e50,e100,rs,adx,atr=[val(r,i) for i in range(8)]
    p60,v60,e20h,e50h,e100h,rsh,adxh,atrh=[val(r,i) for i in range(8,16)]
    c15,c60=val(r,16),val(r,17)
    if min(p15,atr,p60,e20,e50,e100,e20h,e50h,e100h)<=0:return None

    L=S=0;lr=[];sr=[]
    bull=e20h>e50h and p60>e100h
    bear=e20h<e50h and p60<e100h
    bull15=p15>e20 and p15>e50 and p15>e100
    bear15=p15<e20 and p15<e50 and p15<e100

    if bull:L+=22;lr.append("1시간 상승 추세")
    elif bear:S+=22;sr.append("1시간 하락 추세")
    else:return None

    if bull15:L+=18;lr.append("15분 상승 추세")
    elif bear15:S+=18;sr.append("15분 하락 추세")
    else:return None

    if bull and bull15:
        if 52<=rs<=68:L+=12;lr.append(f"RSI {rs:.1f} 정상 상승구간")
        elif rs>70:return None
        if rsh>=50:L+=8;lr.append(f"1시간 RSI {rsh:.1f}")
        if c15>.20:L+=7;lr.append(f"15분 모멘텀 +{c15:.2f}%")
        if c60>.20:L+=7;lr.append(f"1시간 모멘텀 +{c60:.2f}%")
    elif bear and bear15:
        if 32<=rs<=48:S+=12;sr.append(f"RSI {rs:.1f} 정상 하락구간")
        elif rs<30:return None
        if rsh<50:S+=8;sr.append(f"1시간 RSI {rsh:.1f}")
        if c15<-.20:S+=7;sr.append(f"15분 모멘텀 {c15:.2f}%")
        if c60<-.20:S+=7;sr.append(f"1시간 모멘텀 {c60:.2f}%")

    if adx>=20:
        if bull:L+=8;lr.append(f"ADX {adx:.1f} 추세 강도")
        else:S+=8;sr.append(f"ADX {adx:.1f} 추세 강도")
    else:return None

    if adxh>=18:
        if bull:L+=5;lr.append(f"1시간 ADX {adxh:.1f}")
        else:S+=5;sr.append(f"1시간 ADX {adxh:.1f}")

    if v15>100000:
        if bull:L+=6;lr.append("거래량 확인")
        else:S+=6;sr.append("거래량 확인")

    d="LONG" if L>S else "SHORT"
    score=max(L,S)
    if score<THRESHOLD:return None

    risk=max(atr*1.2,p15*.007)
    sl=p15-risk if d=="LONG" else p15+risk
    tp1=p15+risk*1.5 if d=="LONG" else p15-risk*1.5
    tp2=p15+risk*2.5 if d=="LONG" else p15-risk*2.5
    ap=atr/p15*100
    lev=3 if ap>=3 else 5 if ap>=2 else 8 if ap>=1 else 10

    return {
        "symbol":sym(r),"tv":r.get("s",""),"direction":d,"score":score,
        "price":p15,"sl":sl,"tp1":tp1,"tp2":tp2,"rsi":rs,"adx":adx,
        "c15":c15,"c60":c60,"lev":lev,
        "reasons":(lr if d=="LONG" else sr)[:6],
        "time":now().isoformat()
    }

def fmt(x):
    return f"{x:,.2f}" if x>=1000 else f"{x:.4f}" if x>=1 else f"{x:.8f}"

def tg(msg):
    try:
        return requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":msg,"disable_web_page_preview":True},
            timeout=20
        ).status_code==200
    except:return False

def signal_msg(s):
    icon="🟢" if s["direction"]=="LONG" else "🔴"
    title="🔥 강한 시그널" if s["score"]>=STRONG else "⚡ 매매 시그널"
    out=[
        f"{icon} {title}",
        "━━━━━━━━━━━━━━━━━━",
        f"🪙 종목 : #{s['symbol']}",
        f"📌 방향 : {s['direction']}",
        f"⭐ 신뢰도 : {s['score']}/100",
        "",
        "💰 진입 정보",
        f"├ 진입가 : {fmt(s['price'])}",
        f"├ 손절가 : {fmt(s['sl'])}",
        f"├ TP1 : {fmt(s['tp1'])}",
        f"└ TP2 : {fmt(s['tp2'])}",
        "",
        "📊 시장 상태",
        f"├ RSI : {s['rsi']:.1f}",
        f"├ ADX : {s['adx']:.1f}",
        f"├ 15분 : {s['c15']:+.2f}%",
        f"└ 1시간 : {s['c60']:+.2f}%",
        "",
        "🧠 상승/하락 근거"
    ]
    out += [f"• {x}" for x in s["reasons"]]
    out += [
        "",
        f"⚡ 권장 레버리지 : {s['lev']}x",
        f"🔗 {s['tv']}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🎯 TP1 도달 → SL을 진입가로 이동",
        "🎯 TP2 도달 → 시그널 종료",
        "⚠️ 자동주문 없음"
    ]
    return "\n".join(out)

def check_positions(state,rows):
    latest={sym(r):val(r,0) for r in rows}
    for k,p in list(state["positions"].items()):
        x=latest.get(k)
        if not x:continue
        d=p["direction"]
        tp2=x>=p["tp2"] if d=="LONG" else x<=p["tp2"]
        sl=x<=p["sl"] if d=="LONG" else x>=p["sl"]
        tp1=x>=p["tp1"] if d=="LONG" else x<=p["tp1"]

        if tp2:
            tg(
                f"🎯 TP2 도달\n\n"
                f"🪙 #{k} {d}\n"
                f"진입가 : {fmt(p['entry'])}\n"
                f"TP2 : {fmt(p['tp2'])}\n"
                f"현재가 : {fmt(x)}\n\n"
                f"✅ 포지션 추적 종료"
            )
            del state["positions"][k]
            continue

        if sl:
            tg(
                f"🛑 손절가 도달\n\n"
                f"🪙 #{k} {d}\n"
                f"진입가 : {fmt(p['entry'])}\n"
                f"손절가 : {fmt(p['sl'])}\n"
                f"현재가 : {fmt(x)}\n\n"
                f"❌ 포지션 추적 종료"
            )
            del state["positions"][k]
            continue

        if not p.get("tp1_hit") and tp1:
            p["tp1_hit"]=True
            p["sl"]=p["entry"]
            tg(
                f"🎯 TP1 도달\n\n"
                f"🪙 #{k} {d}\n"
                f"진입가 : {fmt(p['entry'])}\n"
                f"TP1 : {fmt(p['tp1'])}\n"
                f"현재가 : {fmt(x)}\n\n"
                f"🔒 손절가 → 진입가 이동\n"
                f"💰 이후 본전 손절 보호"
            )

def main():
    print("="*55)
    print("BTCC FUTURES SIGNAL BOT")
    print("KST:",now().isoformat())
    print("="*55)

    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM secrets missing")

    state=load()
    rows=get_rows()
    print("BTCC ROWS:",len(rows))

    if not rows:
        tg(
            "⚠️ BTCC 데이터 수집 실패\n\n"
            "실제 BTCC 데이터가 확인되지 않아\n"
            "이번 실행에서는 시그널을 생성하지 않았습니다."
        )
        save(state)
        return

    check_positions(state,rows)

    results=[]
    for r in rows:
        try:
            s=analyze(r)
            if s:results.append(s)
        except Exception as e:
            print("ANALYZE:",e)

    results.sort(key=lambda x:x["score"],reverse=True)

    new=[]
    t=time.time()

    for s in results:
        if len(new)>=MAX_ALERTS:break
        key=f"{s['symbol']}:{s['direction']}"

        if t-state["signals"].get(key,0)<COOLDOWN*60:
            continue

        state["signals"][key]=t
        state["positions"][s["symbol"]]={
            "direction":s["direction"],
            "entry":s["price"],
            "sl":s["sl"],
            "tp1":s["tp1"],
            "tp2":s["tp2"],
            "tp1_hit":False,
            "created":s["time"]
        }

        new.append(s)

    for s in new:
        tg(signal_msg(s))
        time.sleep(.4)

    print("QUALIFIED:",len(results))
    print("NEW:",len(new))
    print("ACTIVE:",len(state["positions"]))

    save(state)

if __name__=="__main__":
    main()
