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
            with
