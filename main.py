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
MAX_POSITIONS = 15  # 최대 동시 관리 포지션 수

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
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "active_positions" in data:
                    return data
                elif "active_position" in data and data["active_position"]:
                    return {"active_positions": [data["active_position"]]}
        except Exception:
            pass
    return {"active_positions": []}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        print("💾 bot_state.json 업데이트 완료")
    except Exception as e:
        print(f"상태 저장 중 에러: {e}")

# ---------------------------------------------------------
# 시세 데이터 수집 (BTCC / OKX 백업)
# ---------------------------------------------------------
def get_all_futures_symbols():
    headers = {"User-Agent": "Mozilla/5.0"}
    symbols = []
    try:
        url = "https://api.btcc.com/api/v1/market/tickers"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            ticker_list = data.get("data", []) if isinstance(data, dict) else data
            for item in ticker_list:
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT") or symbol.endswith("_USDT"):
                    clean_symbol = symbol.replace("_", "")
                    symbols.append(clean_symbol)
    except Exception:
        pass

    return sorted(list(set(symbols))) if symbols else ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]

def fetch_market_data(symbol, interval="15m", limit=100):
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # 1. BTCC API
    try:
        formatted_symbol = symbol.replace("USDT", "_USDT") if "_" not in symbol else symbol
        url = f"https://api.btcc.com/api/v1/market/kline?symbol={formatted_symbol}&period={interval}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            raw_data = res.json()
            candles = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data
            if candles:
                df = pd.DataFrame(candles)
                if 'c' in df.columns:
                    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
                
                df['close'] = df['close'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                return df
    except Exception:
        pass

    # 2. OKX API 백업
    try:
        base_asset = symbol.replace("USDT", "").replace("_", "")
        okx_symbol = f"{base_asset}-USDT-SWAP"
        url = f"
