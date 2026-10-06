import os
import json
import requests
import pandas as pd
import ta

# ==========================================
# 텔레그램 인증 및 기본 설정
# ==========================================
TELEGRAM_BOT_TOKEN = "8913250892:AAEQxGKfFC1ru9oJyacy6cdUllER2K0UbiY"
TELEGRAM_CHAT_ID = "-1004443428081"

STATE_FILE = "bot_state.json"

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
# 가격 포맷팅 함수 (소수점 유연하게 표시)
# ---------------------------------------------------------
def format_price(price):
    if price >= 100:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:,.4f}"
    else:
        # 소수점 아래 자릿수가 많은 동전주 대응
        formatted = f"{price:.8f}".rstrip('0').rstrip('.')
        return formatted

# ---------------------------------------------------------
# 상태 파일(bot_state.json) 관리 함수
# ---------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"active_position": None}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"상태 저장 중 에러: {e}")

# ---------------------------------------------------------
# BTCC 거래소 API 기반 종목 및 캔들 데이터 수집
# ---------------------------------------------------------
def get_all_futures_symbols():
    headers = {"User-Agent": "Mozilla/5.0"}
    symbols = []
    try:
        url = "https://api.btcc.com/api/v1/market/tickers"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            # BTCC API 응답 구조에 맞게 종목 추출
            ticker_list = data.get("data", []) if isinstance(data, dict) else data
            for item in ticker_list:
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT") or symbol.endswith("_USDT"):
                    clean_symbol = symbol.replace("_", "")
                    symbols.append(clean_symbol)
    except Exception:
        pass

    return sorted(list(set(symbols))) if symbols else ["BTCUSDT", "ETHUSDT", "TACUSDT", "XRPUSDT", "SOLUSDT"]

def fetch_market_data(symbol, interval="15m", limit=100):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # BTCC 캔들 API 호출
        formatted_symbol = symbol.replace("USDT", "_USDT") if "_" not in symbol else symbol
        url = f"https://api.btcc.com/api/v1/market/kline?symbol={formatted_symbol}&period={interval}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            raw_data = res.json()
            candles = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data
            if candles:
                df = pd.DataFrame(candles)
                # 컬럼명 대응 (BTCC API 규격)
                if 'c' in df.columns:
                    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
                
                df['close'] = df['close'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                return df
    except Exception:
        pass

    # BTCC API 실패 시 백업용 OKX 호출
    try:
        base_asset = symbol.replace("USDT", "").replace("_", "")
        okx_symbol = f"{base_asset}-USDT-SWAP"
        url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&bar={interval}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json().get("data", [])
            if data:
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'v1', 'v2', 'v3'])
                df = df.iloc[::-1].reset_index(drop=True)
                df['close'] = df['close'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                return df
    except Exception:
        pass

    return pd.DataFrame()

# ---------------------------------------------------------
# 변동성(ATR) 기반 레버리지 추천 산출 함수
# ---------------------------------------------------------
def calculate_recommended_leverage(df):
    try:
        atr = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14).iloc[-1]
        latest_price = df.iloc[-1]['close']
        volatility_pct = (atr / latest_price) * 100

        if volatility_pct >= 2.5:
            rec_lev = 3
            risk_level = "⚡ 고변동성 (주의)"
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
# 메인 분석 및 포지션 추적 로직
# --------------------------------
