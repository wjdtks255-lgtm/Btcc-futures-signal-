# main.py
import os,json,time,requests
from datetime import datetime,timezone,timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()
STATE_FILE="bot_state.json"
KST=timezone(timedelta(hours=9))
TV_SCAN="https://scanner.tradingview.com/crypto/scan"
TV_SEARCH="https://symbol-search.tradingview.com/symbol_search/v3/"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.tradingview.com","Referer":"https://www.tradingview.com/"}
THRESHOLD=72
STRONG=85
COOLDOWN=180
MAX_ALERTS=5

COL=[
"close|15","volume|15","EMA20|15","EMA50|15","EMA100|15","RSI|15","ADX|15","ATR|15",
"close|60","volume|60","EMA20|60","EMA50|60","EMA100|60","RSI|60","ADX|60","ATR|60",
"change|15","change|60"
]

def now(): return datetime.now(KST)
def load():
    try:
        with open(STATE_FILE,encoding="utf-8") as f:s=json.load(f)
    except:s={"positions":{},"signals":{}}
    s.setdefault("positions",{});s.setdefault("signals",{})
    return s
def save(s):
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:json.dump(s,f,ensure_ascii=False,indent=2)
    os.replace(STATE_FILE+".tmp",STATE_FILE)

def tv(payload,url=TV_SCAN):
    try:
        r=requests.post(url,json=payload,headers={**H,"Content-Type":"application/json"},timeout=25)
        print("TV",r.status_code,url)
        if r.status_code!=200:return []
        return r.json().get("data",[])
    except Exception as e:
        print("TV ERROR",e);return []

def search_btcc():
    found={}
    queries=["USDT","BTC","ETH","SOL","XRP","ADA","DOGE","AVAX","LINK","SUI","TON","TRX","DOT","LTC","BCH","UNI","AAVE","NEAR","APT","ARB","OP","ATOM","FIL","ETC","HBAR","PEPE","SHIB","BONK","WIF","SAND","MANA","GALA","RAY","INJ","SEI","TIA","TAO","ENA","ONDO","PUMP"]
    for q in queries:
        try:
            p={"text":q,"hl":1,"lang":"en","domain":"production","search_type":"undefined","exchange":"BTCC"}
            r=requests.get(TV_SEARCH,params=p,headers=H,timeout=15)
            if r.status_code!=200:continue
            data=r.json()
            items=data.get("symbols",data if isinstance(data,list) else [])
            for x in items:
                ex=str(x.get("exchange","")).upper()
                typ=str(x.get("type","")).lower()
                ticker=str(x.get("ticker") or x.get("symbol") or "")
                if ex=="BTCC" and ticker:
                    if not ticker.startswith("BTCC:"):ticker="BTCC:"+ticker
                    if ".P" in ticker or "PERPETUAL" in typ:
                        found[ticker]=1
        except Exception as e:print("SEARCH",q,e)
        if len(found)>=500:break
    print("BTCC DISCOVERED:",len(found))
    return list(found)

def scan_symbols(symbols):
    if not symbols:return []
    payload={
        "options":{"lang":"en"},
        "symbols":{"query":"","tickers":symbols,"types":[]},
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,len(symbols)]
    }
    return tv(payload)

def fallback_scan():
    payload={
        "options":{"lang":"en"},
        "markets":["crypto"],
        "filter":[
            {"left":"exchange","operation":"equal","right":"BTCC"}
        ],
        "columns":COL,
        "sort":{"sortBy":"volume|15","sortOrder":"desc"},
        "range":[0,500]
    }
    return tv(payload)

def val(r,i,d=0):
    try:
        x=r.get("d",[])[i]
        return float(x) if x is not None else d
    except:return d

def sym(r):
    return str(r.get("s","")).split(":",1)[-1].replace(".P","")

def analyze(r):
    p15,v15,e20,e50,e100,rs,adx,atr=[val(r,i) for i in range(8)]
    p60,v60,e20h,e50h,e100h,rsh,adxh,atrh=[val(r,i) for i in range(8,16)]
    c15,c60=val(r,16),val(r,17)
    if p15<=0 or atr<=0:return None
    L=S=0;lr=[];sr=[]
    if e20h>e50h:L+=18;lr.append("1H EMA20 > EMA50")
    elif e20h<e50h:S+=18;sr.append("1H EMA20 < EMA50")
    if p60>e100h:L+=10;lr.append("1H 가격 EMA100 상회")
    elif p60<e100h:S+=10;sr.append("1H 가격 EMA100 하회")
    if p15>e20 and p15>e50:L+=18;lr.append("15M EMA20/50 위")
    elif p15<e20 and p15<e50:S+=18;sr.append("15M EMA20/50 아래")
    if p15>e100:L+=7;lr.append("15M EMA100 위")
    elif p15<e100:S+=7;sr.append("15M EMA100 아래")
    if 52<=rs<=72:L+=10;lr.append(f"RSI {rs:.1f}")
    elif 28<=rs<=48:S+=10;sr.append(f"RSI {rs:.1f}")
    if rsh>=50:L+=5;lr.append(f"1H RSI {rsh:.1f}")
    else:S+=5;sr.append(f"1H RSI {rsh:.1f}")
    if adx>=18:
        if L>=S:L+=7;lr.append(f"ADX {adx:.1f}")
        else:S+=7;sr.append(f"ADX {adx:.1f}")
    if adxh>=18:
        if e20h>e50h:L+=5;lr.append(f"1H ADX {adxh:.1f}")
        elif e20h<e50h:S+=5;sr.append(f"1H ADX {adxh:.1f}")
    if c15>.35:L+=8;lr.append(f"15M +{c15:.2f}%")
    elif c15<-.35:S+=8;sr.append(f"15M {c15:.2f}%")
    if c60>.5:L+=5;lr.append(f"1H +{c60:.2f}%")
    elif c60<-.5:S+=5;sr.append(f"1H {c60:.2f}%")
    if v15>100000:
        if L>S:L+=7;lr.append("거래량 확인")
        elif S>L:S+=7;sr.append("거래량 확인")
    d="LONG" if L>=S else "SHORT";score=max(L,S)
    if score<THRESHOLD:return None
    risk=max(atr*1.25,p15*.008)
    sl=p15-risk if d=="LONG" else p15+risk
    tp1=p15+risk*1.5 if d=="LONG" else p15-risk*1.5
    tp2=p15+risk*2.5 if d=="LONG" else p15-risk*2.5
    ap=atr/p15*100
    lev=3 if ap>=3 else 5 if ap>=2 else 8 if ap>=1 else 10
    return {"symbol":sym(r),"tv":r.get("s",""),"direction":d,"score":score,"price":p15,"sl":sl,"tp1":tp1,"tp2":tp2,"rsi":rs,"adx":adx,"c15":c15,"c60":c60,"lev":lev,"reasons":(lr if d=="LONG" else sr)[:5],"time":now().isoformat()}

def fmt(x):
    return f"{x:,.2f}" if x>=1000 else f"{x:.4f}" if x>=1 else f"{x:.8f}"

def tg(msg):
    if not TOKEN or not CHAT_ID:return False
    try:return requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":msg,"disable_web_page_preview":True},timeout=20).status_code==200
    except:return False

def check(state,rows):
    latest={sym(r):val(r,0) for r in rows};closed=[]
    for k,p in list(state["positions"].items()):
        x=latest.get(k)
        if not x:continue
        d=p["direction"]
        hit2=x>=p["tp2"] if d=="LONG" else x<=p["tp2"]
        hitsl=x<=p["sl"] if d=="LONG" else x>=p["sl"]
        hit1=x>=p["tp1"] if d=="LONG" else x<=p["tp1"]
        if hit2:
            tg(f"🎯 BTCC TP2 HIT\n\n#{k} {d}\nEntry : {fmt(p['entry'])}\nTP2 : {fmt(p['tp2'])}\nCurrent : {fmt(x)}")
            closed.append(k);continue
        if hitsl:
            tg(f"🛑 BTCC STOP LOSS\n\n#{k} {d}\nEntry : {fmt(p['entry'])}\nSL : {fmt(p['sl'])}\nCurrent : {fmt(x)}")
            closed.append(k);continue
        if not p.get("tp1_hit") and hit1:
            p["tp1_hit"]=True;p["sl"]=p["entry"]
            tg(f"🎯 BTCC TP1 HIT\n\n#{k} {d}\nEntry : {fmt(p['entry'])}\nTP1 : {fmt(p['tp1'])}\nCurrent : {fmt(x)}\n\n🔒 SL → ENTRY")
    for k in closed:state["positions"].pop(k,None)

def message(ss):
    o=["🚨 BTCC FUTURES SIGNAL","━━━━━━━━━━━━━━━━━━━━","📡 REAL BTCC PERPETUAL","📊 TradingView / BTCC","🕒 "+now().strftime("%Y-%m-%d %H:%M"),""]
    for i,s in enumerate(ss,1):
        icon="🟢" if s["direction"]=="LONG" else "🔴"
        o += [f"{icon} {'🔥 STRONG' if s['score']>=STRONG else '⚡ SIGNAL'} #{i}",f"#{s['symbol']} {s['direction']}",f"⭐ SCORE : {s['score']}/100",f"💰 ENTRY : {fmt(s['price'])}",f"🛑 SL : {fmt(s['sl'])}",f"🎯 TP1 : {fmt(s['tp1'])}",f"🎯 TP2 : {fmt(s['tp2'])}",f"⚡ LEVERAGE : {s['lev']}x",f"📈 RSI : {s['rsi']:.1f}",f"📊 ADX : {s['adx']:.1f}",f"📉 15M : {s['c15']:+.2f}%",f"📉 1H : {s['c60']:+.2f}%","🧠 REASON :",*[f"• {x}" for x in s["reasons"]],f"🔗 {s['tv']}","━━━━━━━━━━━━━━━━━━━━"]
    o.append("⚠️ 자동주문 없음 / BTCC 실제 선물 데이터 기준")
    return "\n".join(o)

def main():
    print("="*55);print("BTCC REAL FUTURES QUANT BOT");print("KST:",now().isoformat());print("="*55)
    if not TOKEN or not CHAT_ID:raise RuntimeError("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing")
    state=load()
    symbols=search_btcc()
    rows=scan_symbols(symbols)
    if not rows:
        print("Direct BTCC symbol scan empty -> fallback")
        rows=fallback_scan()
    print("BTCC REAL ROWS:",len(rows))
    if not rows:
        tg("⚠️ BTCC DATA UNAVAILABLE\n\n실제 BTCC 선물 데이터 수집에 실패하여 시그널을 생성하지 않았습니다.\n\n"+now().strftime("%Y-%m-%d %H:%M KST"))
        save(state);return
    check(state,rows)
    results=[]
    for r in rows:
        try:
            s=analyze(r)
            if s:results.append(s)
        except Exception as e:print("ANALYZE ERROR",e)
    results.sort(key=lambda x:x["score"],reverse=True)
    new=[];t=time.time()
    for s in results[:MAX_ALERTS]:
        key=f"{s['symbol']}:{s['direction']}"
        if t-state["signals"].get(key,0)<COOLDOWN*60:continue
        state["signals"][key]=t
        state["positions"][s["symbol"]]={"direction":s["direction"],"entry":s["price"],"sl":s["sl"],"tp1":s["tp1"],"tp2":s["tp2"],"tp1_hit":False,"created":s["time"]}
        new.append(s)
    if new:tg(message(new))
    print("QUALIFIED:",len(results),"NEW:",len(new),"ACTIVE:",len(state["positions"]))
    save(state)

if __name__=="__main__":main()
