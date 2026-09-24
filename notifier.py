"""
Telegram 通知模組
用法跟你現有 pionex 機器人一致:設定環境變數 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
"""
import os
import requests


def send_telegram_message(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[警告] 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID,跳過推播,僅印出訊息:")
        print(text)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text[:4000]}
    try:
        r = requests.post(url, json=body, timeout=15)
        if r.status_code != 200:
            print(f"[錯誤] Telegram 推播失敗: {r.status_code} {r.text}")
        else:
            print("[完成] Telegram 推播成功")
    except Exception as e:
        # 通知失敗不該讓整個程式中斷,交易本身已經處理完了,推播只是錦上添花
        print(f"[錯誤] Telegram 推播發生例外: {e}")


def notify_order_placed(result):
    direction_label = "多單" if result["direction"] == "long" else "空單"
    text = (
        f"✅ 自動交易下單成功\n"
        f"商品:{result['symbol']}\n"
        f"方向:{direction_label}\n"
        f"數量:{result['qty']}\n"
        f"槓桿:{result['leverage']}倍\n"
        f"進場價:{result['entry_price']}\n"
        f"停損:{result['stop_price']}\n"
        f"停利:{result['target_price']}"
    )
    send_telegram_message(text)


def _format_r(value):
    """把R值格式化成好讀的字串,整數就不顯示小數(例如 +1R),否則去掉多餘的尾端0(例如 +1.5R 而不是 +1.50R)"""
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{rounded:+.0f}R"
    text = f"{rounded:+.2f}".rstrip("0").rstrip(".")
    return f"{text}R"


def notify_trade_closed(info):
    """
    平倉通知(停損或停利觸發時呼叫),同時附上累計勝敗統計跟累計R值
    """
    result_emoji = "🎯" if info["result"] == "停利" else "💥"
    direction_label = "多單" if info["direction"] == "long" else "空單"
    total_trades = info["win_count"] + info["loss_count"]
    win_rate = (info["win_count"] / total_trades * 100) if total_trades > 0 else 0.0
    r_str = _format_r(info["total_r"])
    text = (
        f"{result_emoji} {info['result']}觸發平倉\n"
        f"商品:{info['symbol']}\n"
        f"方向:{direction_label}\n"
        f"進場價:{info['entry_price']}\n"
        f"這筆損益:{info['pnl']:.2f} USDT\n"
        f"—— 累計統計 ——\n"
        f"獲利 {info['win_count']} 單 / 虧損 {info['loss_count']} 單(勝率 {win_rate:.1f}%)\n"
        f"累計淨損益:{info['total_pnl']:.2f} USDT\n"
        f"目前總共 {r_str}"
    )
    send_telegram_message(text)


def notify_risk_halt(today_pnl):
    text = (
        f"🛑 觸發每日虧損上限\n"
        f"今日累計損益:{today_pnl:.2f} USDT\n"
        f"已暫停交易24小時,期間所有交易對都不會進場"
    )
    send_telegram_message(text)


def notify_signal_skipped(symbol, reason):
    """
    跳過本次進場的通知(不是程式錯誤,是正常的市場情況,例如止損距離太寬導致部位低於最小下單量)
    """
    text = (
        f"ℹ️ 本次訊號已跳過,未下單\n"
        f"商品:{symbol}\n"
        f"原因:{reason}"
    )
    send_telegram_message(text)


def notify_error(symbol, error_message):
    text = (
        f"⚠️ 自動交易程式發生錯誤\n"
        f"商品:{symbol}\n"
        f"錯誤訊息:{error_message}"
    )
    send_telegram_message(text)
