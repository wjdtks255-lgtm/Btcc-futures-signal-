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

# 테스트 시 True로 변경하면 이전 포지션 기록을 초기화하여 시그널을 다시 수신할 수 있습니다.
FORCE_RESET_STATE = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ 텔레그램 토큰 또는 Chat ID 설정 누락")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")
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
            print(f"⚠️ 상태 로드 에러: {e}")
    return {"active_positions": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        print("💾 bot_state.json 저장 완료")
    except Exception as e:
        print(f"⚠️ 상태 저장 에러: {e}")

# 바이낸스 선물 시장 전체 종목 수집
def get_binance_futures_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            data = res.json()
            symbols = [
                s["symbol"] for s in data["symbols"]
                if s["quoteAsset"] == "USDT" and s["status"] == "TRADING" and s["contractType"] == "PERPETUAL"
            ]
            if len(symbols) > 50:
                print(f"📊 바이낸스 선물전종목 수집 성공: 총 {len(symbols)}개")
                return sorted(symbols)
    except Exception as e:
        print(f"⚠️ 바이낸스 종목 수집 실패 ({e}), 주요 종목 백업 리스트 사용")

    return [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", 
        "ADAUSDT", "SUIUSDT", "APTUSDT", "NEARUSDT", "LINKUSDT", "BCHUSDT", 
        "BNBUSDT", "DOTUSDT", "FETUSDT", "FILUSDT", "GALAUSDT", "INJUSDT", 
        "LTCUSDT", "OPUSDT", "ORDIUSDT", "SEIUSDT", "TIAUSDT", "TONUSDT", "UNIUSDT"
    ]

# 캔들 데이터 수집 (1차: 바이낸스, 실패 시 2차: 업비트 백업)
def fetch_candles(symbol, interval="15m", limit=100):
    # 1. 바이낸스 API 시도
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                for col in ['close', 'high', 'low', 'open', 'volume']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass

    # 2. 업비트 API 백업 시도
    try:
        base_ticker = symbol.replace("USDT", "")
        if base_ticker.startswith("1000"):
            base_ticker = base_ticker.replace("1000", "")
        
        upbit_market = f"KRW-{base_ticker}"
        url = f"https://api.upbit.com/v1/candles/minutes/15?market={upbit_market}&count={limit}"
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                df = df.rename(columns={
                    'trade_price': 'close',
                    'high_price': 'high',
                    'low_price': 'low',
                    'opening_price': 'open',
                    'candle_acc_trade_volume': 'volume'
                })
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ['close', 'high', 'low', 'open', 'volume']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass

    return pd.DataFrame()

# ATR 기반 동적 레버리지 산출
def calculate_leverage(df):
    try:
        atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14).iloc[-1]
        price = df.iloc[-1]['close']
        vol_pct = (atr / price) * 100

        if vol_pct >= 2.5:
            return 3, "⚡ 초고변동성 (주의)"
        elif vol_pct >= 1.5:
            return 5, "⚖️ 보통 변동성"
        elif vol_pct >= 0.8:
            return 10, "🟢 저변동성 (안정)"
        else:
            return 15, "🛡 극저변동성 (매우 안정)"
    except Exception:
        return 5, "⚖️ 보통 변동성"

def main():
    print("🚀 스캐너 실행 확인 및 테스트 메시지 전송...")
    send_telegram_message("🔔 **BTCC 퀀트 스캐너 정상 작동 중**\n전체 코인 스캔을 시작합니다.")

    state = load_state()
    active_positions = state.get("active_positions", [])
    active_symbols = [p["symbol"] for p in active_positions]

    symbols = get_binance_futures_symbols()
    print(f"🔎 선물 시장 전 코인 스캔 시작... (현재 활성 포지션: {len(active_positions)}/{MAX_POSITIONS})")

    detected_signals = 0

    for symbol in symbols:
        if symbol in active_symbols:
            continue

        df = fetch_candles(symbol)
        if df.empty or len(df) < 50:
            continue

        # 기술적 지표 계산 (EMA 50, RSI 14)
        df['ema50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        entry_price = latest['close']
        rsi_val = latest['rsi']
        ema_val = latest['ema50']

        signal_type = None
        strategy_name = ""

        # 매매 조건
        # LONG: 가격 > EMA50 AND 이전 RSI <= 35 AND RSI 반등
        # SHORT: 가격 < EMA50 AND 이전 RSI >= 65 AND RSI 꺾임
        if entry_price > ema_val and prev['rsi'] <= 35 and rsi_val > prev['rsi']:
            signal_type = "LONG"
            strategy_name = "EMA50 지지 + RSI 과매도 반등"
        elif entry_price < ema_val and prev['rsi'] >= 65 and rsi_val < prev['rsi']:
            signal_type = "SHORT"
            strategy_name = "EMA50 저항 + RSI 과매수 이탈"

        if signal_type:
            detected_signals += 1
            rec_lev, risk_level = calculate_leverage(df)

            if signal_type == "LONG":
                tp1 = entry_price * 1.015
                tp2 = entry_price * 1.030
                sl = entry_price * 0.985
                header = "🟢 **[시그널] LONG 진입 포지션**"
            else:
                tp1 = entry_price * 0.985
                tp2 = entry_price * 0.970
                sl = entry_price * 1.015
                header = "🔴 **[시그널] SHORT 진입 포지션**"

            tp1_roe = 1.50 * rec_lev
            tp2_roe = 3.00 * rec_lev
            sl_roe = 1.50 * rec_lev

            current_count = len(state["active_positions"]) + 1
            msg = (
                f"{header}\n"
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
                f"📌 *포지션 트래킹 중 ({current_count}/{MAX_POSITIONS})*"
            )

            print(f"🎯 시그널 포착! #{symbol} ({signal_type}) -> 전송")
            send_telegram_message(msg)

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
            
            time.sleep(1)

    print(f"✅ BTCC 전종목 스캔 완료 (포착된 시그널: {detected_signals}개 / 현재 보유 포지션: {len(state['active_positions'])}/{MAX_POSITIONS})")

if __name__ == "__main__":
    main()
