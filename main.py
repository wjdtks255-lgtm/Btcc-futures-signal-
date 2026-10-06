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
# 시세 데이터 수집 (BTCC / OKX)
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
# 레버리지 추천 산출
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
# 메인 분석 및 다중 포지션 관리 로직
# ---------------------------------------------------------
def main():
    state = load_state()
    active_positions = state.get("active_positions", [])

    # ---------------------------------------------------------
    # 1. 보유 포지션 감시 및 청산 체크
    # ---------------------------------------------------------
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
                f"📌 *포지션 종료 완료 ({len(remaining_positions)}/{MAX_POSITIONS} 관리 중)*"
            )
            send_telegram_message(message)
        else:
            remaining_positions.append(pos)

    state["active_positions"] = remaining_positions
    save_state(state)

    # ---------------------------------------------------------
    # 2. 신규 포지션 탐색 (15개 채우기 모드)
    # ---------------------------------------------------------
    current_count = len(remaining_positions)
    if current_count >= MAX_POSITIONS:
        print(f"⚠️ [최대 포지션 달성] 현재 {current_count}/{MAX_POSITIONS}개 관리 중입니다.")
        return

    print(f"🔎 신규 시그널 탐색 중... (현재 {current_count}/{MAX_POSITIONS} 슬롯 사용 중)")
    active_symbols = [p["symbol"] for p in remaining_positions]
    all_symbols = get_all_futures_symbols()

    for symbol in all_symbols:
        if symbol in active_symbols:
            continue

        df = fetch_market_data(symbol)
        if df.empty or len(df) < 50:
            continue

        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        df['ema_short'] = ta.trend.ema_indicator(df['close'], window=20)
        df['ema_long'] = ta.trend.ema_indicator(df['close'], window=50)

        macd_indicator = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
        df['macd'] = macd_indicator.macd()
        df['macd_signal'] = macd_indicator.macd_signal()
        df['macd_diff'] = macd_indicator.macd_diff()

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        entry_price = latest['close']
        rsi_val = latest['rsi']

        signal_type = None
        strategy_name = ""

        # 1. RSI 역발상 시그널
        if prev['rsi'] <= 30 and latest['rsi'] > 30:
            signal_type = "LONG"
            strategy_name = "RSI 과매도 반등 추세전환"
        elif prev['rsi'] >= 70 and latest['rsi'] < 70:
            signal_type = "SHORT"
            strategy_name = "RSI 과매수 이탈 반전"

        # 2. EMA 크로스 + MACD 모멘텀 시그널
        elif prev['ema_short'] < prev['ema_long'] and latest['ema_short'] > latest['ema_long']:
            if latest['macd_diff'] > prev['macd_diff'] and latest['rsi'] < 70:
                signal_type = "LONG"
                strategy_name = "EMA 골든크로스 + MACD 모멘텀"

        elif prev['ema_short'] > prev['ema_long'] and latest['ema_short'] < latest['ema_long']:
            if latest['macd_diff'] < prev['macd_diff'] and latest['rsi'] > 30:
                signal_type = "SHORT"
                strategy_name = "EMA 데드크로스 + MACD 모멘텀"

        # 시그널 발생 시 등록 및 알림 발송
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
                print("🏁 최대 포지션 15개가 채워져 이번 스캔을 종료합니다.")
                break

if __name__ == "__main__":
    main()
