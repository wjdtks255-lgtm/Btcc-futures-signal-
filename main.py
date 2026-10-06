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
            print("📱 텔레그램 전문 알림 전송 성공!")
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

        # 변동성에 맞춘 레버리지 추천
        if volatility_pct >= 2.5:
            rec_lev = 3
            risk_level = "⚡ High Volatility (고변동성 주의)"
        elif volatility_pct >= 1.5:
            rec_lev = 5
            risk_level = "⚖️ Medium Volatility (보통)"
        elif volatility_pct >= 0.8:
            rec_lev = 10
            risk_level = "🟢 Low Volatility (안정적)"
        else:
            rec_lev = 15
            risk_level = "🛡 Very Low Volatility (초안정)"

        return rec_lev, risk_level
    except Exception:
        return 5, "⚖️ Medium Volatility (보통)"

# ---------------------------------------------------------
# 메인 분석 및 포지션 추적 로직
# ---------------------------------------------------------
def main():
    state = load_state()
    pos = state.get("active_position")

    # 1. 이미 진입한 포지션이 있는 경우 ➔ 청산 감시
    if pos:
        symbol = pos["symbol"]
        df = fetch_market_data(symbol)
        if df.empty:
            print(f"[{symbol}] 포지션 감시 중 시세 데이터 수집 실패")
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
                close_reason = "🎯 Target 2 (TP2) 도달 - 전량 익절 완료"
                is_closed = True
            elif high_price >= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                save_state(state)
                msg = (
                    f"🎯 **[BTCC QUANT] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **Asset**: #{symbol}\n"
                    f"• **Current Price**: `${latest_price:,.4f}`\n"
                    f"• **Target Yield**: `+1.50%` (추천 {rec_lev}x 적용 시: `+{1.50*rec_lev:.1f}%`)\n"
                    f"💡 *Tip: 잔여 물량 본절가(SL=Entry) 설정 후 TP2 보유 권장*"
                )
                send_telegram_message(msg)
            elif low_price <= sl:
                close_reason = "🛑 Stop-Loss (SL) 이탈 - 포지션 손절 청산"
                is_closed = True

        elif position_type == "SHORT":
            pnl_pct = ((entry_price - latest_price) / entry_price) * 100
            if low_price <= tp2:
                close_reason = "🎯 Target 2 (TP2) 도달 - 전량 익절 완료"
                is_closed = True
            elif low_price <= tp1 and not pos.get("tp1_reached"):
                pos["tp1_reached"] = True
                save_state(state)
                msg = (
                    f"🎯 **[BTCC QUANT] 1차 목표가 달성 (TP1)**\n"
                    f"──────────────────────\n"
                    f"• **Asset**: #{symbol}\n"
                    f"• **Current Price**: `${latest_price:,.4f}`\n"
                    f"• **Target Yield**: `+1.50%` (추천 {rec_lev}x 적용 시: `+{1.50*rec_lev:.1f}%`)\n"
                    f"💡 *Tip: 잔여 물량 본절가(SL=Entry) 설정 후 TP2 보유 권장*"
                )
                send_telegram_message(msg)
            elif high_price >= sl:
                close_reason = "🛑 Stop-Loss (SL) 이탈 - 포지션 손절 청산"
                is_closed = True

        if is_closed:
            status_icon = "🟢" if pnl_pct > 0 else "🔴"
            leveraged_pnl = pnl_pct * rec_lev
            message = (
                f"{status_icon} **[BTCC QUANT] POSITION CLOSED**\n"
                f"──────────────────────\n"
                f"• **Asset**: #{symbol}\n"
                f"• **Type**: `{position_type}`\n"
                f"• **Close Event**: {close_reason}\n"
                f"• **Exit Price**: `${latest_price:,.4f}`\n"
                f"• **Estimated Return**: `{leveraged_pnl:+.2f}%` (추천 {rec_lev}x 기준)\n"
                f"──────────────────────\n"
                f"🔄 *상태 관리자: 포지션 청산 완료. 신규 알파 모니터링을 재개합니다.*"
            )
            send_telegram_message(message)
            state["active_position"] = None
            save_state(state)
            print(f"[{symbol}] 포지션 종료 처리 완료.")
        else:
            print(f"⏳ [{symbol}] {position_type} 진행 중 (현재가: ${latest_price:,.4f}, 수익률: {pnl_pct*rec_lev:+.2f}%)")
        return

    # 2. 보유 포지션이 없는 경우 ➔ 스캔 후 포착
    print("🔍 [BTCC QUANT] 포지션 스캔 및 정밀 분석 구동 중...")
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

        if prev['rsi'] <= 30 and latest['rsi'] > 30:
            signal_type = "LONG"
            strategy_name = "RSI Oversold Mean-Reversion"
        elif prev['ema_short'] < prev['ema_long'] and latest['ema_short'] > latest['ema_long']:
            signal_type = "LONG"
            strategy_name = "EMA Golden Cross Trend Follow"
        elif prev['rsi'] >= 70 and latest['rsi'] < 70:
            signal_type = "SHORT"
            strategy_name = "RSI Overbought Reversal"
        elif prev['ema_short'] > prev['ema_long'] and latest['ema_short'] < latest['ema_long']:
            signal_type = "SHORT"
            strategy_name = "EMA Death Cross Trend Follow"

        if signal_type:
            # 변동성 기반 레버리지 추천 계산
            rec_lev, risk_level = calculate_recommended_leverage(df)

            if signal_type == "LONG":
                tp1 = entry_price * 1.015
                tp2 = entry_price * 1.030
                sl = entry_price * 0.985
                side_header = f"🟢 **[SIGNAL] LONG ENTRY POSITION**"
            else:
                tp1 = entry_price * 0.985
                tp2 = entry_price * 0.970
                sl = entry_price * 1.015
                side_header = f"🔴 **[SIGNAL] SHORT ENTRY POSITION**"

            tp1_roe = 1.50 * rec_lev
            tp2_roe = 3.00 * rec_lev
            sl_roe = 1.50 * rec_lev

            message = (
                f"{side_header}\n"
                f"──────────────────────\n"
                f"• **Exchange**: BTCC Futures\n"
                f"• **Asset Pair**: #{symbol}\n"
                f"• **Timeframe**: `15m` Candle\n"
                f"• **Strategy**: `{strategy_name}`\n"
                f"──────────────────────\n"
                f"⚙️ **[ Volatility & Risk Analysis ]**\n"
                f"• **Market Risk**: {risk_level}\n"
                f"• **Recommended Leverage**: `⚡ {rec_lev}x` (Isolated / 격리)\n"
                f"• **Entry Price**: `${entry_price:,.4f}`\n"
                f"• **RSI (14)**: `{rsi_val:.2f}`\n"
                f"• **Risk / Reward**: `1 : 2` (R:R Ratio)\n"
                f"──────────────────────\n"
                f"🎯 **[ Recommended Targets & Stop ]**\n"
                f"• **TP 1 (50%익절)**: `${tp1:,.4f}` (`+{tp1_roe:.1f}%` ROE)\n"
                f"• **TP 2 (전량익절)**: `${tp2:,.4f}` (`+{tp2_roe:.1f}%` ROE)\n"
                f"• **SL (Stop Loss)**: `${sl:,.4f}` (`-{sl_roe:.1f}%` ROE)\n"
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
            print(f"✅ [{symbol}] {signal_type} (추천 레버리지: {rec_lev}x) 진입 완료")
            break

if __name__ == "__main__":
    main()
