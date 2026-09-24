"""
主執行程式:抓K線 -> 判斷訊號 -> (若有訊號且無持倉) -> 下單

用法:
    python main.py --symbol BTCUSDT --interval 1d --dry-run     # 先用dry-run測試,只印訊號不下單
    python main.py --symbol BTCUSDT --interval 1d               # 正式下單(測試網或正式環境由環境變數決定)
    python main.py --symbol ETHUSDT --interval 4h --dry-run

環境變數(本機測試時用 export 設定,GitHub Actions 則存在 Secrets 裡):
    BINANCE_API_KEY       幣安API Key
    BINANCE_API_SECRET    幣安API Secret
    BINANCE_TESTNET       "true" 或 "false",預設 true(測試網),務必確認清楚目前是哪個環境
"""
import os
import argparse

from binance_futures_client import BinanceFuturesClient
from strategy import compute_signal, BTC_PARAMS, ETH_PARAMS
from order_manager import place_entry_with_sl_tp, QuantityTooSmallError
import risk_manager
import trade_tracker
import notifier

SYMBOL_PARAMS = {
    "BTCUSDT": BTC_PARAMS,
    "ETHUSDT": ETH_PARAMS,
}


def get_client():
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    testnet = os.environ.get("BINANCE_TESTNET", "true").lower() == "true"
    if not api_key or not api_secret:
        raise RuntimeError("請設定環境變數 BINANCE_API_KEY / BINANCE_API_SECRET")
    print(f"連線環境: {'測試網(testnet)' if testnet else '正式環境(mainnet,真金白銀!)'}")
    return BinanceFuturesClient(api_key, api_secret, testnet=testnet)


def has_open_position(client, symbol):
    """
    風控規則:每個交易對各自限制同一時間只允許一筆倉位,BTC跟ETH互不影響。
    """
    positions = client.get_position_risk(symbol)
    for p in positions:
        if p["symbol"] == symbol and float(p["positionAmt"]) != 0:
            return True
    return False


def get_usdt_balance(client):
    balances = client.get_account_balance()
    for b in balances:
        if b["asset"] == "USDT":
            return float(b["availableBalance"])
    return 0.0


def run(args):
    client = get_client()

    # ---- 風控檢查一:每日虧損上限 ----
    halted, today_pnl = risk_manager.check_daily_loss_limit(client)
    if halted:
        if today_pnl is not None:
            notifier.notify_risk_halt(today_pnl)
        print("因觸發每日虧損上限,本次不進行任何交易判斷。")
        return

    # ---- 檢查目前實際持倉狀態,同時用來偵測「上次還在跑、這次已平倉」的事件 ----
    currently_has_position = has_open_position(client, args.symbol)

    closed_info = trade_tracker.check_closed_trade(client, args.symbol, currently_has_position)
    if closed_info:
        print(f"偵測到平倉事件: {closed_info}")
        notifier.notify_trade_closed(closed_info)

    params = SYMBOL_PARAMS[args.symbol]

    print(f"[{args.symbol} / {args.interval}] 抓取K線資料...")
    raw_klines = client.get_klines(args.symbol, args.interval, limit=250)

    # 幣安回傳的最後一根K線通常是「尚未收盤、還在跑」的那根,拿掉它,只用已收盤的資料判斷,
    # 避免用還在變動的資料誤判訊號
    closed_klines = raw_klines[:-1]

    signal = compute_signal(closed_klines, params)

    if signal is None:
        print("本次沒有符合條件的突破訊號,結束。")
        return

    print(f"偵測到訊號: {signal}")

    # ---- 風控檢查二:同一交易對限制單一倉位(BTC跟ETH各自獨立計算) ----
    if currently_has_position:
        print(f"目前 {args.symbol} 已有持倉,依照風控規則跳過本次進場(同一交易對僅允許一筆倉位)。")
        return

    if args.dry_run:
        print("[dry-run模式] 不實際下單,以上為模擬結果,請確認訊號合理後才移除 --dry-run 正式測試。")
        return

    balance = get_usdt_balance(client)
    print(f"目前可用USDT餘額: {balance}")

    try:
        result = place_entry_with_sl_tp(client, args.symbol, signal, balance)
    except QuantityTooSmallError as e:
        # 這不是程式錯誤,是正常的市場情況(止損距離太寬導致部位低於最小下單量),
        # 優雅跳過,用平靜語氣通知,不要當成程式錯誤驚動人
        print(f"[跳過] {e}")
        notifier.notify_signal_skipped(args.symbol, str(e))
        return

    print(f"下單完成: {result}")

    trade_tracker.record_entry(args.symbol, signal["direction"], signal["entry_price"], result["qty"])
    notifier.notify_order_placed(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=list(SYMBOL_PARAMS.keys()))
    parser.add_argument("--interval", required=True, help="例如 1d 或 4h,要跟策略設計的週期一致")
    parser.add_argument("--dry-run", action="store_true", help="只印出訊號,不實際下單,強烈建議先用這個測試")
    args = parser.parse_args()

    try:
        run(args)
    except Exception as e:
        # 讓意外錯誤也能推播通知,方便你不用一直盯著GitHub Actions的執行記錄
        print(f"[錯誤] 執行過程發生例外: {e}")
        notifier.notify_error(args.symbol, str(e))
        raise  # 重新拋出,讓GitHub Actions仍然標記這次執行為失敗,方便追蹤


if __name__ == "__main__":
    main()
