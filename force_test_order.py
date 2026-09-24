"""
強制測試工具:用一個假造的訊號,直接測試下單、槓桿計算、停損停利掛單的完整流程
不需要等真實的Donchian突破訊號出現,方便驗證下單邏輯本身有沒有問題

**只應該在測試網(BINANCE_TESTNET=true)使用,絕對不要在正式環境用這個工具**

用法:
    python force_test_order.py --symbol BTCUSDT --direction long
    python force_test_order.py --symbol ETHUSDT --direction short
"""
import os
import argparse

from binance_futures_client import BinanceFuturesClient
from order_manager import place_entry_with_sl_tp
import trade_tracker
import notifier


def get_client():
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    testnet = os.environ.get("BINANCE_TESTNET", "true").lower() == "true"

    if not api_key or not api_secret:
        raise RuntimeError("請設定環境變數 BINANCE_API_KEY / BINANCE_API_SECRET")

    if not testnet:
        # 安全防呆:這個工具是拿假訊號真的下單,絕對不允許在正式環境執行
        raise RuntimeError(
            "偵測到 BINANCE_TESTNET 不是 true!\n"
            "這個強制測試工具會真的下單,只能在測試網使用。\n"
            "請確認 set BINANCE_TESTNET=true 之後再執行。"
        )

    print("連線環境: 測試網(testnet) —— 已確認安全,可以繼續")
    return BinanceFuturesClient(api_key, api_secret, testnet=testnet)


def get_usdt_balance(client):
    balances = client.get_account_balance()
    for b in balances:
        if b["asset"] == "USDT":
            return float(b["availableBalance"])
    return 0.0


def build_fake_signal(client, symbol, direction):
    """
    用目前市價當作進場價,自己造一個合理的停損停利價位跟數量,
    停損距離故意設得比較寬(市價的1%),避免測試單一下就被隨便波動掃到停損
    """
    mark_price_data = client.get_mark_price(symbol)
    current_price = float(mark_price_data["markPrice"])

    stop_dist_ratio = 0.01  # 停損距離設為市價的1%,純測試用,跟正式策略的ATR停損無關
    risk_usd = 2.0          # 跟正式策略一致,每筆風險固定2 USDT
    rr_ratio = 1.5

    if direction == "long":
        entry_price = current_price
        stop_price = entry_price * (1 - stop_dist_ratio)
        stop_dist = entry_price - stop_price
        target_price = entry_price + rr_ratio * stop_dist
    else:
        entry_price = current_price
        stop_price = entry_price * (1 + stop_dist_ratio)
        stop_dist = stop_price - entry_price
        target_price = entry_price - rr_ratio * stop_dist

    qty = risk_usd / stop_dist

    return {
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "qty": qty,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--direction", required=True, choices=["long", "short"])
    args = parser.parse_args()

    client = get_client()

    # 先檢查有沒有上次測試留下的倉位,在這之間已經被停損或停利觸發平倉了
    has_position_now = False
    positions = client.get_position_risk(args.symbol)
    for p in positions:
        if p["symbol"] == args.symbol and float(p["positionAmt"]) != 0:
            has_position_now = True
    closed_info = trade_tracker.check_closed_trade(client, args.symbol, has_position_now)
    if closed_info:
        print(f"偵測到平倉事件: {closed_info}")
        notifier.notify_trade_closed(closed_info)

    print(f"用目前市價幫 {args.symbol} 建立一個假造的 {args.direction} 訊號...")
    fake_signal = build_fake_signal(client, args.symbol, args.direction)
    print(f"假訊號內容: {fake_signal}")

    balance = get_usdt_balance(client)
    print(f"目前測試網可用USDT餘額: {balance}")

    confirm = input(f"\n即將在測試網對 {args.symbol} 下單({args.direction}),確定要繼續嗎?(輸入 yes 確認): ")
    if confirm.strip().lower() != "yes":
        print("已取消,沒有下單。")
        return

    result = place_entry_with_sl_tp(client, args.symbol, fake_signal, balance)
    print(f"\n下單完成,結果摘要:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    trade_tracker.record_entry(args.symbol, fake_signal["direction"], fake_signal["entry_price"], result["qty"])
    notifier.notify_order_placed(result)

    print(
        f"\n請到 https://testnet.binancefuture.com 網頁上確認:\n"
        f"1. {args.symbol} 是否出現一筆新倉位,槓桿倍數 {result['leverage']}倍 是否合理\n"
        f"2. 是否同時掛了停損單(觸價 {result['stop_price']})跟停利單(觸價 {result['target_price']})\n"
        f"3. 數量 {result['qty']} 是否跟預期一致"
    )


if __name__ == "__main__":
    main()
