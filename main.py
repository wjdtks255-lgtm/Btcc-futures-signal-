import os
import json
import time
import requests
import pandas as pd
import ta

# ==========================================
# 텔레그램 인증 및 기본 설정
# ==========================================
TELEGRAM_BOT_TOKEN = "8913250892:AAEQxGKfFC1ru9oJyacy6cdUllER2K0UbiY"
TELEGRAM_CHAT_ID = "-1004443428081"

STATE_FILE = "bot_state.json"
MAX_POSITIONS = 15  # 최대 동시 관리 포지션 수

# 필요시 True로 설정하면 포지션 상태를 리셋합니다.
FORCE_RESET_STATE = False

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📱 텔레그램 메시지 전송 성공!")
        else:
            print(f"❌ 텔레그램 전송 실패 ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ 텔레그램 전송 중 예외 발생: {e}")

# ---------------------------------------------------------
# 가격 포맷팅 함수
# ---------------------------------------------------------
def format_price(price):
    if price >= 100:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        return f"{price:.8f}".rstrip('0').rstrip('.')

# ---------------------------------------------------------
# 상태 파일(bot_state.json) 관리 함수
# ---------------------------------------------------------
def load_state():
    if FORCE_RESET_STATE:
        print("🔄 [강제 초기화 실행] 기존 포지션 데이터를 리셋합니다.")
        initial_state = {"active_positions": []}
        save_state(initial_state)
        return initial_state

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "active_positions" in data:
                    return data
        except Exception as e:
            print(f"⚠️ 상태 로드 중 에러: {e}")
    return {"active_positions": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        print("💾 bot_state.json 업데이트 완료")
    except Exception as e:
        print(f"⚠️ 상태 저장 중 에러: {e}")

# ---------------------------------------------------------
# 선물 시장 전체 종목 자동 로드 (API 실패 시 350+개 백업 리스트 보장)
# ---------------------------------------------------------
def get_all_futures_symbols():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            symbols = [
                s["symbol"] for s in data["symbols"]
                if s["quoteAsset"] == "USDT" and s["status"] == "TRADING" and s["contractType"] == "PERPETUAL"
            ]
            if len(symbols) > 50:
                print(f"📊 바이낸스 API 성공: 총 {len(symbols)}개 종목 자동 수집 완료")
                return sorted(symbols)
    except Exception as e:
        print(f"⚠️ 종목 목록 API 수집 실패 ({e}), 350+개 백업 전 종목 리스트 사용")

    # API 차단 시 사용할 350개 이상의 선물 코인 전수 백업 리스트
    fallback_symbols = [
        "1000BONKUSDT", "1000CATUSDT", "1000FLOKIUSDT", "1000LUNCUSDT", "1000PEPEUSDT", "1000SATSUSDT", "1000SHIBUSDT", "1000XECUSDT", "1INCHUSDT", "AAVEUSDT",
        "ACEUSDT", "ACHUSDT", "ACTUSDT", "ADAUSDT", "AEVOUSDT", "AGLDUSDT", "AIUSDT", "ALGOUSDT", "ALICEUSDT", "ALPHAUSDT",
        "ALTUSDT", "AMBUSDT", "ANKRUSDT", "APEUSDT", "API3USDT", "APTUSDT", "ARUSDT", "ARBUSDT", "ARKUSDT", "ARKMUSDT",
        "ARPAUSDT", "ASTRUSDT", "ATAUSDT", "ATOMUSDT", "AUCTIONUSDT", "AUDIOUSDT", "AVAXUSDT", "AXLUSDT", "AXSUSDT", "BADGERUSDT",
        "BAKEUSDT", "BALUSDT", "BANANAUSDT", "BANDUSDT", "BATUSDT", "BBUSDT", "BCHUSDT", "BELUSDT", "BICOUSDT", "BIGTIMEUSDT",
        "BLURUSDT", "BNBUSDT", "BNTUSDT", "BNXUSDT", "BOMEUSDT", "BSSVUSDT", "BSVUSDT", "BSWUSDT", "BTCUSDT", "C98USDT",
        "CAKEUSDT", "CELOUSDT", "CELRUSDT", "CFXUSDT", "CHESSUSDT", "CHRUSDT", "CHZUSDT", "CKBUSDT", "COMBOUSDT", "COMPUSDT",
        "COSUSDT", "COTIUSDT", "CRVUSDT", "CTSIUSDT", "CTKUSDT", "CVCUSDT", "CYBERUSDT", "DARUSDT", "DASHUSDT", "DEFIUSDT",
        "DENTUSDT", "DGBUSDT", "DIAUSDT", "DODOUSDT", "DOGEUSDT", "DOGSUSDT", "DOTUSDT", "DRIFTUSDT", "DUSKUSDT", "DYDXUSDT",
        "DYMUSDT", "EDUUSDT", "EGLDUSDT", "EIGENUSDT", "ENAUSDT", "ENJUSDT", "ENSUSDT", "EOSUSDT", "ETCUSDT", "ETHUSDT",
        "ETHFIUSDT", "ETHBTC", "ETHWUSDT", "EUROUSDT", "FARMUSDT", "FETUSDT", "FIDAUSDT", "FILUSDT", "FIOUSDT", "FLMUSDT",
        "FLOWUSDT", "FLUXUSDT", "FORTHUSDT", "FTMUSDT", "FXSUSDT", "GALAUSDT", "GASUSDT", "GHSTUSDT", "GLMRUSDT", "GMTUSDT",
        "GMXUSDT", "GOATUSDT", "GRTUSDT", "GTCUSDT", "HARDUSDT", "HBARUSDT", "HIGHUSDT", "HIPPOUSDT", "HIFIUSDT", "HMSTRUSDT",
        "HOOKUSDT", "HOTUSDT", "ICPUSDT", "ICXUSDT", "IDUSDT", "IDEXUSDT", "ILVUSDT", "INJUSDT", "IOSTUSDT", "IOTAUSDT",
        "IOTXUSDT", "IOUSDT", "JASMYUSDT", "JOEUSDT", "JTOUSDT", "JUPUSDT", "KAIAUSDT", "KAVAUSDT", "KNCUSDT", "KSMUSDT",
        "LDOUSDT", "LEVERUSDT", "LINAUSDT", "LINKUSDT", "LISTAUSDT", "LITUSDT", "LPTUSDT", "LRCUSDT", "LSKUSDT", "LTCUSDT",
        "LUNA2USDT", "MAGICUSDT", "MANAUSDT", "MANTAUSDT", "MASAUSDT", "MASKUSDT", "MAVUSDT", "MBLUSDT", "MBOXUSDT", "MDXUSDT",
        "MEMEUSDT", "METISUSDT", "MINAUSDT", "MKRUSDT", "MOODENGUSDT", "MOVRUSDT", "MTLUSDT", "MYROUSDT", "NEARUSDT", "NEIROUSDT",
        "NEOUSDT", "NFPUSDT", "KNCLUSDT", "NMRUSDT", "NKNUSDT", "NOTUSDT", "NTRNUSDT", "NULSUSDT", "OCEANUSDT", "OGUSDT",
        "OGNUSDT", "OMUSDT", "OMGUSDT", "OMNIUSDT", "ONEUSDT", "ONTUSDT", "OPUSDT", "ORBSUSDT", "ORDIUSDT", "OXTUSDT",
        "PAXGUSDT", "PENDLEUSDT", "PEOPLEUSDT", "PERPUSDT", "PHBUSDT", "PIXELUSDT", "PNUTUSDT", "POLUSDT", "POLXUSDT", "POLYSWARMUSDT",
        "POPCATUSDT", "PORTALUSDT", "POWRUSDT", "PROMUSDT", "PUFFERUSDT", "PYTHUSDT", "QNTUSDT", "QTUMUSDT", "RADUSDT", "RAREUSDT",
        "RAYUSDT", "RDNTUSDT", "REEFUSDT", "RENDERUSDT", "RENUSDT", "REQUSDT", "REZUSDT", "RIFUSDT", "RLCUSDT", "RONINUSDT",
        "ROSEUSDT", "RPLUSDT", "RSRUSDT", "RUNEUSDT", "RVNUSDT", "SAGAUSDT", "SANDUSDT", "SCHECKUSDT", "SCRUSDT", "SEIUSDT",
        "SFPUSDT", "SKLUSDT", "SLPUSDT", "SNTUSDT", "SNXUSDT", "SOLUSDT", "SPELLUSDT", "SPXUSDT", "SSVUSDT", "STEEMUSDT",
        "STGUSDT", "STMXUSDT", "STORJUSDT", "STRAXUSDT", "STRKUSDT", "STXUSDT", "SUIUSDT", "SUNUSDT", "SUPERUSDT", "SUSHIUSDT", "SXPUSDT",
        "SYNUSDT", "SYSUSDT", "TUSDT", "THETAUSDT", "TIAUSDT", "TLMUSDT", "TNSRUSDT", "TOKENUSDT", "TOMOUSDT", "TONUSDT",
        "TRBUSDT", "TROYUSDT", "TRUUSDT", "TRXUSDT", "TURBOUSDT", "TWTUSDT", "UMAUSDT", "UNFIUSDT", "UNIUSDT", "USDCUSDT",
        "USDTUSDT", "USUALUSDT", "USTCUSDT", "VANRYUSDT", "VETUSDT", "VGXUSDT", "VICUSDT", "VIRTUALUSDT", "VITEUSDT", "VOXELUSDT",
        "VTHOUSDT", "WUSDT", "WAXPUSDT", "WLDUSDT", "WIFUSDT", "WOOUSDT", "WRXUSDT", "WTCUSDT", "XAIUSDT", "XECUSDT",
        "XEMUSDT", "XLMUSDT", "XMRUSDT", "XNOUSDT", "XRPUSDT", "XTZUSDT", "XVGUSDT", "XVSUSDT", "YFIUSDT", "YGGUSDT",
        "ZECUSDT", "ZENUSDT", "ZILUSDT", "ZKUSDT", "ZROUSDT", "ZRXUSDT"
    ]
    
    unique_symbols = sorted(list(set(fallback_symbols)))
    print(f"📌 백업 종목 리스트 적용: 총 {len(unique_symbols)}개 종목 스캔 준비 완료")
    return unique_symbols

# ---------------------------------------------------------
# 시세 데이터 수집 (15분 봉)
# ---------------------------------------------------------
def fetch_market_data(symbol, interval="15m", limit=100):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            candles = res.json()
            if candles and isinstance(candles, list):
                df = pd.DataFrame(candles, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                for col in ['close', 'high', 'low', 'open', 'volume']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass

    return pd.DataFrame()

# ---------------------------------------------------------
# 현재 유지 중인 포지션 요약 텍스트
# ---------------------------------------------------------
def generate_active_summary_text(active_positions):
    if not active_positions:
        return "📊 **[현재 유지 중인 시그널]**: 없음 (0개)"

    summary_text = f"📊 **[유지 중인 시그널 현황 ({len(active_positions)}/{MAX_POSITIONS}개)]**\n"
    summary_text += "──────────────────────\n"

    for pos in active_positions:
        symbol = pos["symbol"]
        pos_type = pos["type"]
        entry = pos["entry_price"]
        rec_lev = pos.get("leverage", 5)

        df = fetch_market_data(symbol)
        if not df.empty:
            curr_price = df.iloc[-1]['close']
            if pos_type == "LONG":
                pnl = ((curr_price - entry) / entry) * 100
            else:
                pnl = ((entry - curr_price) / entry) * 100

            leveraged_pnl = pnl * rec_lev
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            
            summary_text += f"• #{symbol} (`{pos_type}` {rec_lev}x)\n"
            summary_text += f"  - 진입가: `${format_price(entry)}` | 현재가: `${format_price(curr_price)}`\n"
            summary_text += f"  - 수익률: {pnl_icon} `{leveraged_pnl:+.2f}%` (원금 기준 `{pnl:+.2f}%`)\n\n"
        else:
            summary_text += f"• #{symbol} (`{pos_type}` {rec_lev}x) - 진입가: `${format_price(entry)}`\n\n"

    return summary_text.strip()

# ---------------------------------------------------------
# 레버리지 추천 산출
# ---------------------------------------------------------
def calculate_recommended_leverage(df):
    try:
        atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14).iloc[-1]
        latest_price = df.iloc[-1]['close']
        volatility_pct = (atr / latest_price) * 100

        if volatility_pct >= 2.5:
            rec_lev = 3
            risk_level = "⚡ 초고변동성 (주의)"
        elif volatility_pct >= 1.5:
            rec_lev = 5
            risk_level = "⚖️ 보통 변동성"
        elif volatility_pct >= 0.8:
            rec_lev = 10
            risk_level = "🟢 저변동성 (안정)"
        else:
            rec_lev = 15
            risk_level = "🛡 극저변동성 (매우 안정)"

        return rec_lev, risk_level
    except Exception:
        return 5, "⚖️ 보통 변동성"

# ---------------------------------------------------------
# 메인 분석 및 포지션 관리 로직
# ---------------------------------------------------------
def main():
    # 0. 선물 시장 상장 전체 종목 수집 (350개 이상 보장)
    all_symbols = get_all_futures_symbols()

    # 1. 상태 로드 및 보유 포지션 관리
    state = load_state()
    active_positions = state.get("active_positions", [])

    remaining_positions = []
    for pos in active_positions:
        symbol = pos["symbol"]
        print(f"🔍 기존 포지션 ({symbol}) 모니터링 중...")
        df = fetch_market_data(symbol)
        if df.empty:
            remaining_positions.append(pos)
            continue

        latest_price = df.iloc[-1]['close']
        high_price = df.iloc[-1]['high']
        low_price = df.iloc[-1]['low']

        position_type = pos["type"]
        entry_price = pos["entry_price"]
        rec_lev = pos.get("leverage", 5)
        tp1 = pos["tp1"]
        tp2 = pos["tp2"]
        sl = pos["sl"]

        is_closed = False
        close_reason = ""
        pnl_pct = 0.0

        if position_type == "LONG":
            pnl_pct = ((latest_price - entry_price) / entry_price) * 100
            if high_price >= tp2:
                close_reason = "🎯 2차 목표가 (TP2) 도달 - 전량 익절 완료"
                is_closed = True
            elif high_price >= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                msg = (
                    f"🎯 **[BTCC 퀀트] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **종목**: #{symbol}\n"
                    f"• **현재가**: `${format_price(latest_price)}`\n"
                    f"• **목표 수익률**: `+1.50%` (추천 {rec_lev}배 적용 시: `+{1.50*rec_lev:.1f}%`)\n"
                    f"──────────────────────\n"
                    f"💡 *팁: 잔여 물량 본절가(SL=진입가) 설정 후 TP2 보유 권장*"
                )
                send_telegram_message(msg)
            elif low_price <= sl:
                close_reason = "🛑 손절가 (SL) 이탈 - 포지션 손절 청산"
                is_closed = True

        elif position_type == "SHORT":
            pnl_pct = ((entry_price - latest_price) / entry_price) * 100
            if low_price <= tp2:
                close_reason = "🎯 2차 목표가 (TP2) 도달 - 전량 익절 완료"
                is_closed = True
            elif low_price <= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                msg = (
                    f"🎯 **[BTCC 퀀트] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **종목**: #{symbol}\n"
                    f"• **현재가**: `${format_price(latest_price)}`\n"
                    f"• **목표 수익률**: `+1.50%` (추천 {rec_lev}배 적용 시: `+{1.50*rec_lev:.1f}%`)\n"
                    f"──────────────────────\n"
                    f"💡 *팁: 잔여 물량 본절가(SL=진입가) 설정 후 TP2 보유 권장*"
                )
                send_telegram_message(msg)
            elif high_price >= sl:
                close_reason = "🛑 손절가 (SL) 이탈 - 포지션 손절 청산"
                is_closed = True

        if is_closed:
            status_icon = "🟢" if pnl_pct > 0 else "🔴"
            leveraged_pnl = pnl_pct * rec_lev
            
            message = (
                f"{status_icon} **[BTCC 퀀트] 포지션 종료 알림**\n"
                f"──────────────────────\n"
                f"• **종목**: #{symbol}\n"
                f"• **포지션**: `{position_type}`\n"
                f"• **종료 사유**: {close_reason}\n"
                f"• **청산가**: `${format_price(latest_price)}`\n"
                f"• **추정 수익률**: `{leveraged_pnl:+.2f}%` (추천 {rec_lev}배 기준)\n"
                f"──────────────────────\n"
            )
            
            temp_remaining = [p for p in remaining_positions if p["symbol"] != symbol]
            active_summary = generate_active_summary_text(temp_remaining)
            message += f"\n{active_summary}"
            
            send_telegram_message(message)
        else:
            remaining_positions.append(pos)

    state["active_positions"] = remaining_positions
    save_state(state)

    # 2. BTCC 전체 코인 스캔 (350개+)
    current_count = len(remaining_positions)
    print(f"🔎 선물 시장 전 코인 총 {len(all_symbols)}개 전수 스캔 시작... (현재 {current_count}/{MAX_POSITIONS} 사용 중)")
    active_symbols = [p["symbol"] for p in remaining_positions]

    for symbol in all_symbols:
        if symbol in active_symbols:
            continue

        df = fetch_market_data(symbol)
        if df.empty or len(df) < 50:
            continue

        # 지표 산출
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=20)
        df['ema_long'] = ta.trend.ema_indicator(df['close'], window=50)
        df['ema_trend'] = ta.trend.ema_indicator(df['close'], window=200)

        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
        df['bb_hband'] = bb.bollinger_hband()
        df['bb_lband'] = bb.bollinger_lband()

        macd_indicator = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
        df['macd'] = macd_indicator.macd()
        df['macd_signal'] = macd_indicator.macd_signal()
        df['macd_diff'] = macd_indicator.macd_diff()

        stoch_rsi = ta.momentum.StochRSIIndicator(df['close'], window=14, smooth1=3, smooth2=3)
        df['stoch_k'] = stoch_rsi.stochrsi_k() * 100
        df['stoch_d'] = stoch_rsi.stochrsi_d() * 100

        atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=10)
        kc_middle = ta.trend.ema_indicator(df['close'], window=20)
        df['kc_hband'] = kc_middle + (atr * 1.5)
        df['kc_lband'] = kc_middle - (atr * 1.5)

        df['vol_ma'] = df['volume'].rolling(window=5).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        entry_price = latest['close']
        rsi_val = latest['rsi']

        vol_confirmed = latest['volume'] > (latest['vol_ma'] * 1.1)

        signal_type = None
        strategy_name = ""

        # 5대 다중 전략 조건
        if prev['rsi'] <= 40 and latest['rsi'] > 40 and prev['low'] <= prev['bb_lband']:
            signal_type = "LONG"
            strategy_name = "볼린저 하단 반등 + RSI 과매도 회복"

        elif prev['rsi'] >= 60 and latest['rsi'] < 60 and prev['high'] >= prev['bb_hband']:
            signal_type = "SHORT"
            strategy_name = "볼린저 상단 반전 + RSI 과매수 이탈"

        elif latest['ema_short'] > latest['ema_long'] and prev['macd_diff'] < latest['macd_diff'] and latest['macd_diff'] > 0:
            if 38 <= latest['rsi'] <= 68 and vol_confirmed and latest['close'] > latest['ema_trend']:
                signal_type = "LONG"
                strategy_name = "200 EMA 정배열 + MACD 수급 돌파"

        elif latest['ema_short'] < latest['ema_long'] and prev['macd_diff'] > latest['macd_diff'] and latest['macd_diff'] < 0:
            if 32 <= latest['rsi'] <= 62 and vol_confirmed and latest['close'] < latest['ema_trend']:
                signal_type = "SHORT"
                strategy_name = "200 EMA 역배열 + MACD 이탈 모멘텀"

        elif latest['close'] > latest['ema_short'] and latest['ema_short'] > latest['ema_long']:
            if prev['stoch_k'] <= 25 and latest['stoch_k'] > 25 and latest['stoch_k'] > latest['stoch_d']:
                signal_type = "LONG"
                strategy_name = "스토캐스틱 RSI 과매도 + EMA 정배열 눌림목 반등"

        elif latest['close'] < latest['ema_short'] and latest['ema_short'] < latest['ema_long']:
            if prev['stoch_k'] >= 75 and latest['stoch_k'] < 75 and latest['stoch_k'] < latest['stoch_d']:
                signal_type = "SHORT"
                strategy_name = "스토캐스틱 RSI 과매수 + EMA 역배열 반락"

        elif latest['close'] > latest['kc_hband'] and prev['close'] <= prev['kc_hband'] and vol_confirmed:
            if latest['rsi'] >= 50:
                signal_type = "LONG"
                strategy_name = "켈트너 채널 상단 돌파 + 수급 실린 변동성 폭발"

        elif latest['close'] < latest['kc_lband'] and prev['close'] >= prev['kc_lband'] and vol_confirmed:
            if latest['rsi'] <= 50:
                signal_type = "SHORT"
                strategy_name = "켈트너 채널 하단 이탈 + 하락 변동성 폭발"

        elif prev['macd'] < 0 and latest['macd'] >= 0 and latest['macd'] > latest['macd_signal']:
            if latest['close'] > latest['ema_short']:
                signal_type = "LONG"
                strategy_name = "MACD Zero-Line 상향 돌파 + 상승 전환"

        elif prev['macd'] > 0 and latest['macd'] <= 0 and latest['macd'] < latest['macd_signal']:
            if latest['close'] < latest['ema_short']:
                signal_type = "SHORT"
                strategy_name = "MACD Zero-Line 하향 이탈 + 하락 전환"

        # 시그널 발생 처리
        if signal_type:
            rec_lev, risk_level = calculate_recommended_leverage(df)

            if signal_type == "LONG":
                tp1 = entry_price * 1.015
                tp2 = entry_price * 1.030
                sl = entry_price * 0.985
                side_header = f"🟢 **[시그널] LONG 진입 포지션**"
            else:
                tp1 = entry_price * 0.985
                tp2 = entry_price * 0.970
                sl = entry_price * 1.015
                side_header = f"🔴 **[시그널] SHORT 진입 포지션**"

            tp1_roe = 1.50 * rec_lev
            tp2_roe = 3.00 * rec_lev
            sl_roe = 1.50 * rec_lev

            current_count += 1
            message = (
                f"{side_header}\n"
                f"──────────────────────\n"
                f"• **거래소**: BTCC 선물\n"
                f"• **종목**: #{symbol}\n"
                f"• **타임프레임**: `15분` 캔들\n"
                f"• **매매 전략**: `{strategy_name}`\n"
                f"──────────────────────\n"
                f"⚙️ **[ 변동성 및 위험도 분석 ]**\n"
                f"• **시장 위험도**: {risk_level}\n"
                f"• **추천 레버리지**: `⚡ {rec_lev}배` (격리)\n"
                f"• **진입가**: `${format_price(entry_price)}`\n"
                f"• **RSI (14)**: `{rsi_val:.2f}`\n"
                f"• **손익비**: `1 : 2` (R:R 비율)\n"
                f"──────────────────────\n"
                f"🎯 **[ 추천 목표가 및 손절가 ]**\n"
                f"• **1차 목표가 (50% 익절)**: `${format_price(tp1)}` (`+{tp1_roe:.1f}%` ROE)\n"
                f"• **2차 목표가 (전량 익절)**: `${format_price(tp2)}` (`+{tp2_roe:.1f}%` ROE)\n"
                f"• **손절가 (손절)**: `${format_price(sl)}` (`-{sl_roe:.1f}%` ROE)\n"
                f"──────────────────────\n"
                f"📌 *멀티 관리 모드: 현재 {current_count}/{MAX_POSITIONS}개 포지션 트래킹 중*"
            )
            send_telegram_message(message)

            new_position = {
                "symbol": symbol,
                "type": signal_type,
                "entry_price": entry_price,
                "leverage": rec_lev,
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "tp1_reached": False
            }
            state["active_positions"].append(new_position)
            active_symbols.append(symbol)
            save_state(state)

            if current_count >= MAX_POSITIONS:
                print("🏁 최대 포지션 15개가 채워져 스캔을 완료합니다.")
                break

    print(f"✅ BTCC 전종목 스캔 완료 (현재 보유 포지션: {len(state['active_positions'])}/{MAX_POSITIONS})")

if __name__ == "__main__":
    main()
