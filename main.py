import os
import json
import requests
import pandas as pd
import ta

# 환경 변수 설정
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8913250892:AAEQxGKfFC1ru9oJyacy6cdUllER2K0UbiY")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004443428081")

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
        if response.status_code != 200:
            print(f"전송 실패: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"텔레그램 전송 중 에러 발생: {e}")

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
# 시세 데이터 및 종목 목록 수집
# ---------------------------------------------------------
def get_all_futures_symbols():
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    symbols = []
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json().get("data", [])
            for item in data:
                inst_id = item.get("instId", "")
                if inst_id.endswith("-USDT-SWAP"):
                    symbols.append(f"{inst_id.split('-')[0]}USDT")
    except Exception:
        pass

    return sorted(list(set(symbols))) if symbols else ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT"]

def fetch_market_data(symbol, interval="15m", limit=100):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        base_asset = symbol.replace("USDT", "")
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
# 메인 분석 및 포지션 상태 추적 로직
# ---------------------------------------------------------
def main():
    state = load_state()
    pos = state.get("active_position")

    # 1. 이미 진입한 포지션이 있는 경우 ➔ 청산(목표가/손절가) 여부만 감시
    if pos:
        symbol = pos["symbol"]
        df = fetch_market_data(symbol)
        if df.empty:
            print(f"[{symbol}] 포지션 감시 중 시세 데이터를 불러오지 못했습니다.")
            return

        latest_price = df.iloc[-1]['close']
        high_price = df.iloc[-1]['high']
        low_price = df.iloc[-1]['low']

        position_type = pos["type"] # LONG or SHORT
        tp1 = pos["tp1"]
        tp2 = pos["tp2"]
        sl = pos["sl"]

        is_closed = False
        close_reason = ""

        if position_type == "LONG":
            if high_price >= tp2:
                close_reason = f"🎯 **2차 목표가 (TP2) 달성!** (`${tp2:,.4f}`)"
                is_closed = True
            elif high_price >= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                save_state(state)
                send_telegram_message(f"🎯 **BTCC 선물 [{symbol}] 1차 목표가 (TP1) 달성!**\n• 현재가: `${latest_price:,.4f}`")
            elif low_price <= sl:
                close_reason = f"🛑 **손절가 (SL) 도달 및 청산** (`${sl:,.4f}`)"
                is_closed = True

        elif position_type == "SHORT":
            if low_price <= tp2:
                close_reason = f"🎯 **2차 목표가 (TP2) 달성!** (`${tp2:,.4f}`)"
                is_closed = True
            elif low_price <= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                save_state(state)
                send_telegram_message(f"🎯 **BTCC 선물 [{symbol}] 1차 목표가 (TP1) 달성!**\n• 현재가: `${latest_price:,.4f}`")
            elif high_price >= sl:
                close_reason = f"🛑 **손절가 (SL) 도달 및 청산** (`${sl:,.4f}`)"
                is_closed = True

        if is_closed:
            message = (
                f"🏁 **BTCC 선물 [{symbol}] 포지션 종료 알림**\n\n"
                f"• **진입 유형**: {position_type}\n"
                f"• **종료 사유**: {close_reason}\n"
                f"• **최종 가격**: `${latest_price:,.4f}`\n\n"
                f"✨ 포지션이 종료되어 다음 종목 탐색을 다시 시작합니다."
            )
            send_telegram_message(message)
            state["active_position"] = None
            save_state(state)
            print(f"[{symbol}] 포지션 종료 처리 완료. 다음 탐색 재개.")
        else:
            print(f"⏳ [{symbol}] {position_type} 포지션 진행 중... (현재가: ${latest_price:,.4f})")
        return

    # 2. 보유 포지션이 없는 경우 ➔ 전 종목 스캔 후 최초 1개 종목 잡히면 즉시 탐색 중단
    print("🔍 보유 중인 포지션 없음. 전 종목 스캔 중...")
    all_symbols = get_all_futures_symbols()

    for symbol in all_symbols:
        df = fetch_market_data(symbol)
        if df.empty or len(df) < 50:
            continue

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

        # 첫 번째 시그널 발생 시 ➔ 신규 포지션 등록 후 탐색 즉시 중단(Break)
        if signal_type:
            if signal_type == "LONG":
                tp1 = entry_price * 1.015
                tp2 = entry_price * 1.030
                sl = entry_price * 0.985
                header = f"🟢 **BTCC 선물 [{symbol}] LONG 진입 시그널**"
            else:
                tp1 = entry_price * 0.985
                tp2 = entry_price * 0.970
                sl = entry_price * 1.015
                header = f"🔴 **BTCC 선물 [{symbol}] SHORT 진입 시그널**"

            message = (
                f"{header}\n\n"
                f"• **거래소**: BTCC 선물\n"
                f"• **종목**: {symbol}\n"
                f"• **근거**: {reason}\n\n"
                f"**[ 🎯 목표가 / 손절가 설정 ]**\n"
                f"• **진입가**: `${entry_price:,.4f}`\n"
                f"• **1차 목표가 (TP1)**: `${tp1:,.4f}`\n"
                f"• **2차 목표가 (TP2)**: `${tp2:,.4f}`\n"
                f"• **손절가 (SL)**: `${sl:,.4f}`\n\n"
                f"📌 해당 종목 종료 전까지 추가 탐색을 대기합니다."
            )
            send_telegram_message(message)

            # 포지션 상태 저장
            state["active_position"] = {
                "symbol": symbol,
                "type": signal_type,
                "entry_price": entry_price,
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "tp1_reached": False
            }
            save_state(state)
            print(f"✅ [{symbol}] {signal_type} 진입 완료! 다른 종목 탐색 대기 상태로 전환합니다.")
            break

if __name__ == "__main__":
    main()
