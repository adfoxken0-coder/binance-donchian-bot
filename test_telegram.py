"""
測試腳本:純粹測試Telegram通知有沒有正確送達,不會有任何幣安操作,不會下單。

用法:
    python test_telegram.py
"""
from datetime import datetime, timezone, timedelta
import notifier

TAIPEI_TZ = timezone(timedelta(hours=8))


def main():
    now_str = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"✅ 這是一則測試訊息\n"
        f"時間:{now_str} (UTC+8)\n"
        f"如果你收到這則訊息,代表 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 設定正確,通知功能正常運作。"
    )
    notifier.send_telegram_message(text)
    print("測試訊息已嘗試發送,請檢查Telegram是否收到。")


if __name__ == "__main__":
    main()
