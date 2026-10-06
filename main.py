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
# ---------------------------------------------------------
def main():
    state = load_state()
    pos = state.get("active_position")

    # 1. 포지션 청산 감시 모드
    if pos:
        symbol = pos["symbol"]
        df = fetch_market_data(symbol)
        if df.empty:
            return

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
                save_state(state)
                msg = (
                    f"🎯 **[BTCC 퀀트] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **종목**: #{symbol}\n"
                    f"• **현재가**: `${latest_price:,.4f}`\n"
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
                save_state(state)
                msg = (
                    f"🎯 **[BTCC 퀀트] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **종목**: #{symbol}\n"
                    f"• **현재가**: `${latest_price:,.4f}`\n"
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
                f"• **청산가**: `${latest_price:,.4f}`\n"
                f"• **추정 수익률**: `{leveraged_pnl:+.2f}%` (추천 {rec_lev}배 기준)\n"
                f"──────────────────────\n"
                f"📌 *포지션 종료 완료. 신규 종목 탐색을 재개합니다.*"
            )
            send_telegram_message(message)
            state["active_position"] = None
            save_state(state)
        return

    # 2. 신규 포지션 탐색 모드
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
        rsi_val = latest['rsi']

        signal_type = None
        strategy_name = ""

        # 롱 조건
        if prev['rsi'] <= 30 and latest['rsi'] > 30:
            signal_type = "LONG"
            strategy_name = "RSI 과매도 반등 추세전환"
        elif prev['ema_short'] < prev['ema_long'] and latest['ema_short'] > latest['ema_long']:
            signal_type = "LONG"
            strategy_name = "EMA 골든크로스 추세추종"

        # 숏 조건
        elif prev['rsi'] >= 70 and latest['rsi'] < 70:
            signal_type = "SHORT"
            strategy_name = "RSI 과매수 이탈 반전"
        elif prev['ema_short'] > prev['ema_long'] and latest['ema_short'] < latest['ema_long']:
            signal_type = "SHORT"
            strategy_name = "EMA 데드크로스 추세추종"

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

            # 영어 레이아웃 서식 100% 유지 + 한글 번역
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
                f"• **진입가**: `${entry_price:,.4f}`\n"
                f"• **RSI (14)**: `{rsi_val:.2f}`\n"
                f"• **손익비**: `1 : 2` (R:R 비율)\n"
                f"──────────────────────\n"
                f"🎯 **[ 추천 목표가 및 손절가 ]**\n"
                f"• **1차 목표가 (50% 익절)**: `${tp1:,.4f}` (`+{tp1_roe:.1f}%` ROE)\n"
                f"• **2차 목표가 (전량 익절)**: `${tp2:,.4f}` (`+{tp2_roe:.1f}%` ROE)\n"
                f"• **손절가 (손절)**: `${sl:,.4f}` (`-{sl_roe:.1f}%` ROE)\n"
                f"──────────────────────\n"
                f"📌 *단일 종목 집중 관리 모드: 포지션 종료 전까지 추가 탐색을 대기합니다.*"
            )
            send_telegram_message(message)

            state["active_position"] = {
                "symbol": symbol,
                "type": signal_type,
                "entry_price": entry_price,
                "leverage": rec_lev,
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "tp1_reached": False
            }
            save_state(state)
            break

if __name__ == "__main__":
    main()
