"""
下單模組:根據策略訊號,設定槓桿、下市價單進場、同時掛停損停利單
"""
import math
from binance_futures_client import BinanceFuturesClient


class QuantityTooSmallError(Exception):
    """
    這不是程式錯誤,是正常的市場情況:這次訊號的止損距離太寬,
    以固定風險金額換算出來的部位,小於幣安該交易對的最小下單量,
    這筆訊號應該優雅跳過,而不是當成程式錯誤處理。
    """
    pass

# 幣安對每個交易對的數量/價格精度不同。這裡先列出BTC/ETH常見精度方便先跑起來,
# 正式使用前建議改成呼叫 client.get_exchange_info() 動態抓取,避免幣安調整精度規則後程式跟不上
SYMBOL_PRECISION = {
    "BTCUSDT": {"qty_precision": 3, "price_precision": 1},
    "ETHUSDT": {"qty_precision": 3, "price_precision": 2},
}

# 安全上限:不管理論算出多少倍槓桿,實際下單絕對不超過這個倍數
MAX_LEVERAGE_CAP = 20

# 只用帳戶餘額的一部分當可用保證金基準(預設50%),留緩衝避免爆倉,
# 也避免單一筆交易把全部資金鎖住
DEFAULT_SAFETY_MARGIN_RATIO = 0.5


def round_step(value, precision):
    factor = 10 ** precision
    return math.floor(value * factor) / factor


def calc_leverage(entry_price, qty, account_balance, safety_margin_ratio=DEFAULT_SAFETY_MARGIN_RATIO):
    """根據理論倉位大小反推需要的槓桿倍數,並套用安全上限"""
    notional = entry_price * qty
    usable_balance = account_balance * safety_margin_ratio
    if usable_balance <= 0:
        raise ValueError("可用保證金為0或負數,無法計算槓桿,請檢查帳戶餘額")
    required_leverage = notional / usable_balance
    return max(1, min(MAX_LEVERAGE_CAP, math.ceil(required_leverage)))


def place_entry_with_sl_tp(client: BinanceFuturesClient, symbol: str, signal: dict, account_balance: float):
    """
    signal 來自 strategy.compute_signal() 的回傳:
    { "direction", "entry_price", "stop_price", "target_price", "qty" }

    回傳下單結果摘要,方便記錄/通知用
    """
    precision = SYMBOL_PRECISION.get(symbol, {"qty_precision": 3, "price_precision": 2})
    qty_p = precision["qty_precision"]
    price_p = precision["price_precision"]

    qty = round_step(signal["qty"], qty_p)
    if qty <= 0:
        min_step = 10 ** (-qty_p)
        raise QuantityTooSmallError(
            f"以本次風險金額換算出的部位為 {signal['qty']:.6f},"
            f"低於 {symbol} 最小下單量 {min_step}(可能是這次止損距離偏寬,超出目前風險預算能覆蓋的範圍)"
        )

    leverage = calc_leverage(signal["entry_price"], qty, account_balance)
    client.set_leverage(symbol, leverage)

    entry_side = "BUY" if signal["direction"] == "long" else "SELL"
    exit_side = "SELL" if signal["direction"] == "long" else "BUY"

    # 1. 市價進場
    entry_order = client.new_order(
        symbol=symbol, side=entry_side, order_type="MARKET", quantity=qty,
    )

    stop_price = round_step(signal["stop_price"], price_p)
    target_price = round_step(signal["target_price"], price_p)

    # 2. 停損單(STOP_MARKET,觸價後市價全部平倉)
    # 注意:幣安2025年12月起,條件單(STOP_MARKET/TAKE_PROFIT_MARKET)必須改用
    # Algo Order API(new_algo_order),舊的 new_order 端點會回傳錯誤代碼 -4120
    stop_order = client.new_algo_order(
        symbol=symbol, side=exit_side, order_type="STOP_MARKET",
        trigger_price=stop_price, close_position=True,
    )

    # 3. 停利單(TAKE_PROFIT_MARKET,觸價後市價全部平倉)
    tp_order = client.new_algo_order(
        symbol=symbol, side=exit_side, order_type="TAKE_PROFIT_MARKET",
        trigger_price=target_price, close_position=True,
    )

    return {
        "symbol": symbol,
        "direction": signal["direction"],
        "leverage": leverage,
        "qty": qty,
        "entry_price": signal["entry_price"],
        "stop_price": stop_price,
        "target_price": target_price,
        "entry_order_id": entry_order.get("orderId"),
        "stop_algo_id": stop_order.get("algoId"),
        "tp_algo_id": tp_order.get("algoId"),
    }
