import os,json,time,requests,pandas as pd,ta
from datetime import datetime,timezone

TOKEN=os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()
STATE_FILE="bot_state.json"

MIN_SCORE=68
STRONG_SCORE=80
COOLDOWN_MIN=180
BASE="https://fapi.binance.com"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json"}

def tg(text):
    if not TOKEN or not CHAT_ID:
        print("❌ Telegram Secrets 없음")
        return False
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT_ID,"text":text,"parse_mode":"Markdown"},
            timeout=10
        )
        print(f"Telegram: {r.status_code}")
        if r.status_code!=200:
            print("Telegram:",r.text[:500])
        return r.status_code==200
    except Exception as e:
        print("Telegram 오류:",e)
        return False

def api(path,params=None,timeout=10):
    try:
        r=requests.get(
            BASE+path,
            params=params,
            headers=HEADERS,
            timeout=timeout
        )

        print(f"API {path} -> HTTP {r.status_code}")

        if r.status_code!=200:
            print("API 오류:",r.text[:500])
            return None

        try:
            data=r.json()
        except Exception:
            print("❌ JSON 변환 실패:",r.text[:500])
            return None

        if isinstance(data,dict) and data.get("code") not in (None,0):
            print("❌ Binance 오류:",data)
            return None

        return data

    except requests.RequestException as e:
        print("❌ API 연결 오류:",e)
        return None
    except Exception as e:
        print("❌ API 오류:",e)
        return None

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE,encoding="utf-8") as f:
                s=json.load(f)
            s.setdefault("positions",{})
            s.setdefault("signals",{})
            return s
    except Exception as e:
        print("State 로드 오류:",e)
    return {"positions":{},"signals":{}}

def save_state(s):
    try:
        with open(STATE_FILE,"w",encoding="utf-8") as f:
            json.dump(s,f,ensure_ascii=False,indent=2)
    except Exception as e:
        print("State 저장 오류:",e)

def get_symbols():
    print("📡 Binance Futures 종목 정보 요청...")

    data=api("/fapi/v1/exchangeInfo",timeout=15)

    if data is None:
        print("❌ exchangeInfo 응답 없음")
        return []

    if not isinstance(data,dict):
        print("❌ exchangeInfo 형식 오류")
        print("응답:",str(data)[:500])
        return []

    symbols_data=data.get("symbols")

    if not isinstance(symbols_data,list):
        print("❌ exchangeInfo에 symbols 배열 없음")
        print("응답 키:",list(data.keys()))
        print("응답:",str(data)[:1000])
        return []

    symbols=[]

    for x in symbols_data:
        try:
            if (
                x.get("quoteAsset")=="USDT"
                and x.get("status")=="TRADING"
                and x.get("contractType")=="PERPETUAL"
            ):
                symbols.append(x["symbol"])
        except:
            continue

    symbols=sorted(set(symbols))

    print(f"✅ USDT 무기한 선물 {len(symbols)}개")

    return symbols

def candles(symbol,interval,limit=160):
    data=api(
        "/fapi/v1/klines",
        {
            "symbol":symbol,
            "interval":interval,
            "limit":limit
        },
        timeout=8
    )

    if not isinstance(data,list) or len(data)<80:
        return pd.DataFrame()

    try:
        df=pd.DataFrame(data,columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tb_base",
            "tb_quote","ignore"
        ])

        for c in ["open","high","low","close","volume"]:
            df[c]=pd.to_numeric(df[c],errors="coerce")

        return df.dropna()
    except:
        return pd.DataFrame()

def indicators(df):
    df=df.copy()

    df["ema20"]=ta.trend.ema_indicator(df.close,20)
    df["ema50"]=ta.trend.ema_indicator(df.close,50)
    df["ema100"]=ta.trend.ema_indicator(df.close,100)
    df["rsi"]=ta.momentum.rsi(df.close,14)
    df["atr"]=ta.volatility.average_true_range(
        df.high,df.low,df.close,14
    )
    df["adx"]=ta.trend.adx(
        df.high,df.low,df.close,14
    )
    df["vol_ma"]=df.volume.rolling(20).mean()
    df["mom"]=df.close.pct_change(4)*100

    return df.dropna()

def analyze(h1,m15):
    h=h1.iloc[-1]
    m=m15.iloc[-1]
    p=m15.iloc[-2]

    L=0
    S=0
    lr=[]
    sr=[]

    if h.ema20>h.ema50:
        L+=20
        lr.append("1H 상승추세")
    elif h.ema20<h.ema50:
        S+=20
        sr.append("1H 하락추세")

    if h.close>h.ema100:
        L+=10
        lr.append("1H 100EMA 위")
    elif h.close<h.ema100:
        S+=10
        sr.append("1H 100EMA 아래")

    if m.close>m.ema20>m.ema50:
        L+=15
        lr.append("15M EMA 정배열")
    elif m.close<m.ema20<m.ema50:
        S+=15
        sr.append("15M EMA 역배열")

    if m.rsi>p.rsi:
        if 38<=m.rsi<=68:
            L+=15
            lr.append(f"RSI 상승 {m.rsi:.1f}")
        if p.rsi<40:
            L+=8
            lr.append("과매도 반등")

    elif m.rsi<p.rsi:
        if 32<=m.rsi<=62:
            S+=15
            sr.append(f"RSI 하락 {m.rsi:.1f}")
        if p.rsi>60:
            S+=8
            sr.append("과매수 이탈")

    if m.volume>m.vol_ma*1.15:
        if m.close>p.close:
            L+=10
            lr.append("거래량 증가")
        elif m.close<p.close:
            S+=10
            sr.append("거래량 증가")

    if m.mom>0.20:
        L+=10
        lr.append(f"모멘텀 +{m.mom:.2f}%")
    elif m.mom<-0.20:
        S+=10
        sr.append(f"모멘텀 {m.mom:.2f}%")

    if m.adx>=18:
        if L>S:
            L+=5
            lr.append(f"ADX {m.adx:.1f}")
        elif S>L:
            S+=5
            sr.append(f"ADX {m.adx:.1f}")

    if L>=S:
        return "LONG",L,lr

    return "SHORT",S,sr

def risk_levels(price,atr,direction):
    risk=max(atr*1.25,price*0.008)

    if direction=="LONG":
        return (
            price-risk,
            price+risk*1.5,
            price+risk*2.5
        )

    return (
        price+risk,
        price-risk*1.5,
        price-risk*2.5
    )

def leverage(atr,price):
    v=atr/price*100

    if v>=3:
        return 3,"초고변동"
    if v>=2:
        return 5,"고변동"
    if v>=1:
        return 8,"보통"

    return 10,"저변동"

def fmt(p):
    if p>=100:
        return f"{p:,.2f}"
    if p>=1:
        return f"{p:,.4f}"

    return f"{p:.8f}".rstrip("0").rstrip(".")

def signal_id(symbol,direction):
    return f"{symbol}_{direction}"

def cooldown_ok(state,symbol,direction):
    old=state["signals"].get(
        signal_id(symbol,direction)
    )

    if not old:
        return True

    try:
        t=datetime.fromisoformat(old)
        age=(
            datetime.now(timezone.utc)-t
        ).total_seconds()/60

        return age>=COOLDOWN_MIN

    except:
        return True

def track_positions(state):
    if not state["positions"]:
        return

    print(
        f"📌 기존 포지션 "
        f"{len(state['positions'])}개 추적"
    )

    remove=[]

    for symbol,p in list(
        state["positions"].items()
    ):
        df=candles(symbol,"15m",40)

        if df.empty:
            continue

        price=float(df.close.iloc[-1])
        direction=p["direction"]

        if direction=="LONG":

            if price<=p["sl"]:
                hit="SL"
            elif price>=p["tp2"]:
                hit="TP2"
            elif (
                price>=p["tp1"]
                and not p.get("tp1_hit")
            ):
                hit="TP1"
            else:
                hit=None

        else:

            if price>=p["sl"]:
                hit="SL"
            elif price<=p["tp2"]:
                hit="TP2"
            elif (
                price<=p["tp1"]
                and not p.get("tp1_hit")
            ):
                hit="TP1"
            else:
                hit=None

        if not hit:
            continue

        if hit=="TP1":

            p["tp1_hit"]=True
            p["sl"]=p["entry"]

            tg(
                f"🎯 *BTCC TP1 도달*\n\n"
                f"• 종목: `#{symbol}`\n"
                f"• 방향: `{direction}`\n"
                f"• 현재가: `${fmt(price)}`\n"
                f"• TP1: `${fmt(p['tp1'])}`\n"
                f"• 🔒 SL → 진입가 이동"
            )

        else:

            icon="💰" if hit=="TP2" else "🛑"

            tg(
                f"{icon} *BTCC 포지션 종료*\n\n"
                f"• 종목: `#{symbol}`\n"
                f"• 방향: `{direction}`\n"
                f"• 결과: `{hit}`\n"
                f"• 가격: `${fmt(price)}`"
            )

            remove.append(symbol)

    for symbol in remove:
        state["positions"].pop(symbol,None)

def main():

    print("="*50)
    print("🚀 BTCC FUTURES QUANT SCANNER")
    print("="*50)

    if not TOKEN or not CHAT_ID:
        print(
            "❌ TELEGRAM_TOKEN / "
            "TELEGRAM_CHAT_ID 없음"
        )
        return

    if not tg(
        "🟢 *BTCC 스캐너 실행 확인*\n\n"
        "Telegram 연결 정상입니다."
    ):
        return

    state=load_state()

    track_positions(state)
    save_state(state)

    symbols=get_symbols()

    if not symbols:

        msg=(
            "❌ *선물 종목 데이터 수집 실패*\n\n"
            "Binance Futures API에서 "
            "정상적인 종목 목록을 받지 못했습니다.\n\n"
            "GitHub Actions 로그를 확인해주세요."
        )

        tg(msg)

        print(
            "❌ 종목이 0개라 스캔을 중단합니다."
        )

        return

    print(
        f"🔎 전체 {len(symbols)}개 "
        f"종목 스캔 시작"
    )

    candidates=[]

    for i,symbol in enumerate(symbols,1):

        try:

            h1=candles(
                symbol,
                "1h",
                160
            )

            m15=candles(
                symbol,
                "15m",
                160
            )

            if h1.empty or m15.empty:
                continue

            h1=indicators(h1)
            m15=indicators(m15)

            if len(h1)<110 or len(m15)<110:
                continue

            direction,score,reasons=analyze(
                h1,
                m15
            )

            if score<MIN_SCORE:
                continue

            if symbol in state["positions"]:
                continue

            if not cooldown_ok(
                state,
                symbol,
                direction
            ):
                continue

            price=float(
                m15.close.iloc[-1]
            )

            atr=float(
                m15.atr.iloc[-1]
            )

            sl,tp1,tp2=risk_levels(
                price,
                atr,
                direction
            )

            lev,risk_name=leverage(
                atr,
                price
            )

            candidates.append({
                "symbol":symbol,
                "direction":direction,
                "score":score,
                "price":price,
                "sl":sl,
                "tp1":tp1,
                "tp2":tp2,
                "leverage":lev,
                "risk_name":risk_name,
                "reasons":reasons
            })

            print(
                f"🎯 {symbol} "
                f"{direction} "
                f"SCORE={score}"
            )

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

        time.sleep(0.12)

        if i%50==0:

            print(
                f"진행률 "
                f"{i}/{len(symbols)}"
            )

    candidates.sort(
        key=lambda x:x["score"],
        reverse=True
    )

    print("="*50)
    print(
        f"🎯 후보 시그널 "
        f"{len(candidates)}개"
    )
    print("="*50)

    sent=0

    for x in candidates:

        symbol=x["symbol"]
        direction=x["direction"]
        price=x["price"]
        score=x["score"]

        icon=(
            "🟢"
            if direction=="LONG"
            else "🔴"
        )

        grade=(
            "🔥 강력"
            if score>=STRONG_SCORE
            else "⚡ 유효"
        )

        risk=abs(
            price-x["sl"]
        )

        rr2=abs(
            x["tp2"]-price
        )/risk

        reasons=" · ".join(
            x["reasons"][:6]
        )

        msg=(
            f"{icon} *BTCC 선물 "
            f"{direction} 시그널*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 종목: `#{symbol}`\n"
            f"• 등급: `{grade}`\n"
            f"• 퀀트 점수: `{score}/100`\n"
            f"• 분석: `1H + 15M`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 *진입*\n"
            f"• 진입가: "
            f"`${fmt(price)}`\n"
            f"• 레버리지: "
            f"`{x['leverage']}x`\n"
            f"• 변동성: "
            f"`{x['risk_name']}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *목표 / 손절*\n"
            f"• TP1: "
            f"`${fmt(x['tp1'])}`\n"
            f"• TP2: "
            f"`${fmt(x['tp2'])}`\n"
            f"• SL: "
            f"`${fmt(x['sl'])}`\n"
            f"• R:R: "
            f"`1:{rr2:.1f}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 *시그널 근거*\n"
            f"{reasons}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ 기술적 분석 기반 시그널"
        )

        if tg(msg):

            now=datetime.now(
                timezone.utc
            ).isoformat()

            state["signals"][
                signal_id(
                    symbol,
                    direction
                )
            ]=now

            state["positions"][symbol]={
                "direction":direction,
                "entry":price,
                "sl":x["sl"],
                "tp1":x["tp1"],
                "tp2":x["tp2"],
                "tp1_hit":False,
                "score":score,
                "time":now
            }

            save_state(state)
            sent+=1

        time.sleep(0.3)

    save_state(state)

    tg(
        f"✅ *BTCC 스캔 완료*\n\n"
        f"• 전체 종목: `{len(symbols)}`개\n"
        f"• 신규 시그널: `{sent}`개\n"
        f"• 추적 포지션: "
        f"`{len(state['positions'])}`개"
    )

    print(
        f"✅ 완료 | "
        f"전체 {len(symbols)} | "
        f"신호 {sent} | "
        f"포지션 "
        f"{len(state['positions'])}"
    )

if __name__=="__main__":
    main()
