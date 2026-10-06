import os
import requests
import pandas as pd
import ta

# 환경 변수에서 Secrets 값 가져오기
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("텔레그램 시그널 전송 성공!")
        else:
            print(f"전송 실패: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"에러 발생: {e}")

def fetch_market_data(symbol="BTCUSDT", interval="15m", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    data = response.json()
    
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return df

def analyze_and_signal():
    symbol = "BTCUSDT"
    interval = "15m"
    df = fetch_market_data(symbol=symbol, interval=interval)
    
    # 지표 계산 (RSI 14, EMA 20, EMA 50)
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    df['ema_short'] = ta.trend.ema_indicator(df['close'], window=20)
    df['ema_long'] = ta.trend.ema_indicator(df['close'], window=50)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal_type = None
    reason = ""
    
    # 롱 조건
    if prev['rsi'] <= 30 and latest['rsi'] > 30:
        signal_type = "🟢 **BTCC LONG (매수) 시그널**"
        reason = "RSI 과매도 구간(30 이하) 탈출"
    elif prev['ema_short'] < prev['ema_long'] and latest['ema_short'] > latest['ema_long']:
        signal_type = "🟢 **BTCC LONG (매수) 시그널**"
        reason = "EMA 20/50 골든크로스 발생"

    # 숏 조건
    elif prev['rsi'] >= 70 and latest['rsi'] < 70:
        signal_type = "🔴 **BTCC SHORT (매도) 시그널**"
        reason = "RSI 과매수 구간(70 이상) 이탈"
    elif prev['ema_short'] > prev['ema_long'] and latest['ema_short'] < latest['ema_long']:
        signal_type = "🔴 **BTCC SHORT (매도) 시그널**"
        reason = "EMA 20/50 데드크로스 발생"
        
    if signal_type:
        message = (
            f"{signal_type}\n\n"
            f"• **종목**: {symbol}\n"
            f"• **근거**: {reason}\n"
            f"• **현재가**: `${latest['close']:,.2f}`\n"
            f"• **RSI (14)**: `{latest['rsi']:.2f}`\n"
            f"• **타임프레임**: {interval}\n"
        )
        send_telegram_message(message)
    else:
        print(f"[{symbol}] 현재 특이 시그널이 없습니다. (현재가: {latest['close']}, RSI: {latest['rsi']:.2f})")

if __name__ == "__main__":
    analyze_and_signal()
