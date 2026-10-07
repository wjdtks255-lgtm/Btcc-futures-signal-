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
MAX_POSITIONS = 15

FORCE_RESET_STATE = True

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return False

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
            return True
        else:
            print(f"❌ 텔레그램 전송 실패 ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"❌ 텔레그램 전송 중 예외 발생: {e}")
        return False

def format_price(price):
    if price >= 100:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        return f"{price:.8f}".rstrip('0').rstrip('.')

def load_state():
    if FORCE_RESET_STATE:
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
    return sorted(list(set(fallback_symbols)))

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

def main():
    print("🚀 스캐너 실행 확인 및 텔레그램 테스트 메시지 발송 시작...")
    send_telegram_message("🔔 **[BTCC 퀀트] 스캐너 정상 작동 중**\n전체 코인 스캔을 시작합니다.")

    all_symbols = get_all_futures_symbols()
    state = load_state()
    active_positions = state.get("active_positions", [])

    current_count = len(active_positions)
    print(f"🔎 선물 시장 전 코인 총 {len(all_symbols)}개 전수 스캔 시작... (현재 {current_count}/{MAX_POSITIONS} 사용 중)")
    active_symbols = [p["symbol"] for p in active_positions]

    detected_signals = 0

    for symbol in all_symbols:
        if symbol in active_symbols:
            continue

        df = fetch_market_data(symbol)
        if df.empty or len(df) < 50:
            continue

        # 지표 산출
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        latest = df.iloc[-1]
        entry_price = latest['close']
        rsi_val = latest['rsi']

        signal_type = None
        strategy_name = ""

        # 🧪 [테스트 전용 포착 조건] - RSI 지표 범위 기준 유효 시그널 테스트
        if rsi_val >= 55:
            signal_type = "SHORT"
            strategy_name = "RSI 상승 구간 모멘텀 시그널"
        elif rsi_val <= 45:
            signal_type = "LONG"
            strategy_name = "RSI 하락 구간 모멘텀 시그널"

        # 시그널 발생 처리
        if signal_type:
            detected_signals += 1
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
            
            print(f"🎯 시그널 포착! #{symbol} ({signal_type}) - 텔레그램 전송 중...")
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

            # 테스트용으로 시그널 3개까지만 전송 후 종료
            if detected_signals >= 3:
                print("🧪 테스트용 시그널 3개 포착 완료로 스캔을 종료합니다.")
                break

    print(f"✅ BTCC 전종목 스캔 완료 (포착된 시그널: {detected_signals}개 / 현재 보유 포지션: {len(state['active_positions'])}/{MAX_POSITIONS})")

if __name__ == "__main__":
    main()
