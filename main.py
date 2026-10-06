import os
import requests
import pandas as pd
import ta

# 환경 변수에서 Secrets 값 가져오기
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8913250892:AAEQxGKfFC1ru9oJyacy6cdUllER2K0UbiY")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004443428081")

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
            print("텔레그램 시그널 전송 성공!")
        else:
            print(f"전송 실패: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"텔레그램 전송 중 에러 발생: {e}")

def fetch_btcc_market_data(symbol="BTCUSDT", interval="15m", limit=100):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    # 1차 시도: OKX 선물 API (GitHub Actions 클라우드 환경에서 차단 없음)
    try:
        okx_interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H"}
        bar = okx_interval_map.get(interval, "15m")
        okx_symbol = f"{symbol[:3]}-{symbol[3:]}-SWAP"  # BTC-USDT-SWAP
        
        url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&bar={bar}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=8)
        
        if res.status_code == 200:
            data = res.json()
            raw_list = data.get("data", [])
            if raw_list:
                # OKX format: [ts, open, high, low, close, volume, ...]
                df = pd.DataFrame(raw_list, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'])
                df = df.iloc[::-1].reset_index(drop=True)
                df['close'] = df['close'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                return df
    except Exception as e:
        print(f"1차 선물 API 호출 예외 발생: {e}")

    # 2차 시도: Gate.io 선물 API (보완 엔드포인트)
    try:
        gate_symbol = f"{symbol[:3]}_{symbol[3:]}"  # BTC_USDT
        url = f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={gate_symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, headers=headers, timeout=8)
        
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                # Gate.io format: [t, v, c, h, l, o]
                df = pd.DataFrame(data)
                df.rename(columns={'c': 'close', 'h': 'high', 'l': 'low'}, inplace=True)
                df['close'] = df['close'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                return df
    except Exception as e:
        print(f"2차 선물 API 호출 예외 발생: {e}")

    return pd.DataFrame()

def analyze_and_signal():
    symbol = "BTCUSDT"
    interval = "15m"
    
    df = fetch_btcc_market_data(symbol=symbol, interval=interval)
    
    if df.empty or len(df) < 50:
        print(f"❌ [{symbol}] 선물 시세 데이터를 불러오지 못했습니다.")
        return

    # 지표 계산 (RSI 14, EMA 20, EMA 50)
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    df['ema_short'] = ta.trend.ema_indicator(df['close'], window=20)
    df['ema_long'] = ta.trend.ema_indicator(df['close'], window=50)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    entry_price = latest['close']
    signal_type = None
    reason = ""
    
    # 롱 조건
    if prev['rsi'] <= 30 and latest['rsi'] > 30:
        signal_type = "LONG"
        reason = "RSI 과매도 구간(30 이하) 탈출"
    elif prev['ema_short'] < prev['ema_long'] and latest['ema_short'] > latest['ema_long']:
        signal_type = "LONG"
        reason = "EMA 20/50 골든크로스 발생"

    # 숏 조건
    elif prev['rsi'] >= 70 and latest['rsi'] < 70:
        signal_type = "SHORT"
        reason = "RSI 과매수 구간(70 이상) 이탈"
    elif prev['ema_short'] > prev['ema_long'] and latest['ema_short'] < latest['ema_long']:
        signal_type = "SHORT"
        reason = "EMA 20/50 데드크로스 발생"
        
    if signal_type:
        if signal_type == "LONG":
            tp1 = entry_price * 1.015  # +1.5%
            tp2 = entry_price * 1.030  # +3.0%
            sl = entry_price * 0.985   # -1.5%
            header = "🟢 **BTCC 선물 LONG (매수) 시그널**"
        else:
            tp1 = entry_price * 0.985  # -1.5%
            tp2 = entry_price * 0.970  # -3.0%
            sl = entry_price * 1.015   # +1.5%
            header = "🔴 **BTCC 선물 SHORT (매도) 시그널**"

        message = (
            f"{header}\n\n"
            f"• **거래소**: BTCC 선물\n"
            f"• **종목**: {symbol} ({interval})\n"
            f"• **근거**: {reason}\n\n"
            f"**[ 🎯 가격 및 목표가 설정 ]**\n"
            f"• **진입가**: `${entry_price:,.2f}`\n"
            f"• **1차 목표가 (TP1)**: `${tp1:,.2f}` (+1.5% 익절)\n"
            f"• **2차 목표가 (TP2)**: `${tp2:,.2f}` (+3.0% 익절)\n"
            f"• **손절가 (SL)**: `${sl:,.2f}` (-1.5% 리스크)\n\n"
            f"**[ ⚡ 권장 레버리지 ]**\n"
            f"• **추천 레버리지**: `5x ~ 10x`\n"
            f"• **RSI (14)**: `{latest['rsi']:.2f}`\n"
        )
        send_telegram_message(message)
    else:
        print(f"[BTCC 선물 - {symbol}] 현재 특이 시그널이 없습니다. (현재가: ${latest['close']:,.2f}, RSI: {latest['rsi']:.2f})")

if __name__ == "__main__":
    analyze_and_signal()
