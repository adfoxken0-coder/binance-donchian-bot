"""
風控模組:每日最大虧損限制
- 以台北時間(UTC+8)為一天的界線,累計當天的真實淨損益(已實現盈虧+手續費+資金費率)
- 虧損達到門檻(預設6 USDT)時,寫入暫停狀態,24小時內不再進場
- 狀態存在 risk_state.json,設計上會被 GitHub Actions commit 回 repo 保存(第6步再處理)
"""
import os
import json
import time
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))
STATE_FILE = os.path.join(os.path.dirname(__file__), "risk_state.json")

DAILY_MAX_LOSS_USD = 6.0     # 每日最大虧損金額(USDT),累計淨損益低於這個負值就停止交易
HALT_DURATION_HOURS = 24     # 觸發後暫停交易的時數


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _today_taipei_str():
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")


def _taipei_day_start_ms():
    """回傳今天(台北時間)00:00對應的UTC毫秒時間戳,用來查詢從今天開始的損益"""
    now_taipei = datetime.now(TAIPEI_TZ)
    day_start_taipei = now_taipei.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start_taipei.timestamp() * 1000)


def is_trading_halted(state):
    """單純檢查目前是否處於暫停狀態,不呼叫API,速度快"""
    halt_until = state.get("halt_until_ms")
    if halt_until is None:
        return False, None
    now_ms = int(time.time() * 1000)
    if now_ms < halt_until:
        remaining_hours = (halt_until - now_ms) / 1000 / 3600
        return True, remaining_hours
    return False, None


def check_daily_loss_limit(client):
    """
    主要進入點:每次執行main.py時呼叫這個函數。
    1. 先檢查是否已經在暫停狀態中(不需要重新計算)
    2. 若沒有暫停,查詢今天以來的累計淨損益,判斷是否需要觸發暫停

    回傳: (是否暫停中或剛觸發暫停, 今日累計損益或None)
    """
    state = load_state()

    already_halted, remaining_hours = is_trading_halted(state)
    if already_halted:
        print(f"[風控] 目前處於每日虧損暫停狀態,剩餘約 {remaining_hours:.1f} 小時解除")
        return True, None

    day_start_ms = _taipei_day_start_ms()
    income_records = client.get_income_history(start_time=day_start_ms, limit=1000)
    today_pnl = sum(float(r["income"]) for r in income_records)

    state["last_check_date"] = _today_taipei_str()
    state["last_today_pnl"] = today_pnl

    if today_pnl <= -abs(DAILY_MAX_LOSS_USD):
        halt_until_ms = int(time.time() * 1000) + HALT_DURATION_HOURS * 3600 * 1000
        state["halt_until_ms"] = halt_until_ms
        state["halt_triggered_pnl"] = today_pnl
        save_state(state)
        print(f"[風控] 今日累計損益 {today_pnl:.2f} USDT,已達虧損上限 -{DAILY_MAX_LOSS_USD} USDT,"
              f"暫停交易 {HALT_DURATION_HOURS} 小時")
        return True, today_pnl

    save_state(state)
    print(f"[風控] 今日累計損益 {today_pnl:.2f} USDT,未達虧損上限,可正常交易")
    return False, today_pnl
