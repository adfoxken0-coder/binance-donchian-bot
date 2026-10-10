"""
交易追蹤模組:
1. 記錄目前開倉的資訊(position_tracker.json),用來偵測「上次還在跑、這次已經平倉」的狀態變化
2. 平倉發生時,查詢該筆倉位的已實現淨損益,依正負判斷是停利還是停損觸發,更新累計統計(trade_stats.json)

因為程式是靠GitHub Actions每次重新啟動執行,沒有常駐程序即時監控訂單狀態,
所以用「這次執行 vs 上次執行」的持倉狀態差異,反推這段期間是否發生了平倉事件。
兩個狀態檔都會被workflow commit回repo,跨執行保留記錄。
"""
import os
import json
import time

POSITION_FILE = os.path.join(os.path.dirname(__file__), "position_tracker.json")
STATS_FILE = os.path.join(os.path.dirname(__file__), "trade_stats.json")

# 1R = 每筆固定風險金額,跟 strategy.py 裡 risk_usd 的設定一致(BTC/ETH都是10.0)
R_UNIT_USD = 10.0


def _load(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_entry(symbol, direction, entry_price, qty):
    """下單成功後呼叫,記錄這筆倉位的開倉資訊,供下次執行時偵測是否平倉用"""
    tracker = _load(POSITION_FILE, {})
    tracker[symbol] = {
        "open": True,
        "direction": direction,
        "entry_price": entry_price,
        "qty": qty,
        "opened_at_ms": int(time.time() * 1000),
    }
    _save(POSITION_FILE, tracker)


SIGNAL_KEY = "_last_signal_candle"


def signal_already_handled(symbol, candle_open_ms):
    """同一根K線的訊號只處理一次:排程每20分鐘跑一次,同一根已收盤K線會被重複看到"""
    tracker = _load(POSITION_FILE, {})
    return tracker.get(SIGNAL_KEY, {}).get(symbol) == candle_open_ms


def mark_signal_handled(symbol, candle_open_ms):
    tracker = _load(POSITION_FILE, {})
    tracker.setdefault(SIGNAL_KEY, {})[symbol] = candle_open_ms
    _save(POSITION_FILE, tracker)


def check_closed_trade(client, symbol, currently_has_position):
    """
    比對記錄的開倉狀態跟目前實際持倉狀態,判斷這個交易對是否有一筆倉位
    在這次執行之間平倉了。若有,查詢損益、判斷停損/停利、更新累計統計。

    回傳: dict(平倉資訊 + 更新後的累計統計)或 None(沒有平倉事件發生)
    """
    tracker = _load(POSITION_FILE, {})
    record = tracker.get(symbol)

    if record is None or not record.get("open"):
        # 沒有本程式自己記錄在跑的倉位(可能從沒下過單,或是上次已經處理過平倉了)
        return None

    if currently_has_position:
        # 記錄顯示有倉位在跑,實際也還有倉位,還沒平倉,不用處理
        return None

    # 記錄顯示有倉位在跑,但現在已經沒有持倉了 -> 這段期間平倉了(停損或停利觸發)
    income_records = client.get_income_history(
        start_time=record["opened_at_ms"], symbol=symbol, limit=1000,
    )
    trade_pnl = sum(float(r["income"]) for r in income_records)

    stats = _load(STATS_FILE, {"win_count": 0, "loss_count": 0, "total_pnl": 0.0})
    is_win = trade_pnl > 0

    if is_win:
        stats["win_count"] = stats.get("win_count", 0) + 1
    else:
        stats["loss_count"] = stats.get("loss_count", 0) + 1
    stats["total_pnl"] = stats.get("total_pnl", 0.0) + trade_pnl
    _save(STATS_FILE, stats)

    # 標記這筆倉位已平倉,避免下次執行重複計算
    record["open"] = False
    tracker[symbol] = record
    _save(POSITION_FILE, tracker)

    return {
        "symbol": symbol,
        "direction": record["direction"],
        "entry_price": record["entry_price"],
        "result": "停利" if is_win else "停損",
        "pnl": trade_pnl,
        "win_count": stats["win_count"],
        "loss_count": stats["loss_count"],
        "total_pnl": stats["total_pnl"],
        "total_r": stats["total_pnl"] / R_UNIT_USD,
    }
