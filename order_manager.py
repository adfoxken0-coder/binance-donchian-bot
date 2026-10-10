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


class SignalStaleError(Exception):
    """
    訊號已過期:下單當下的標記價格已經貼近或越過這筆訊號的停損/停利價,
    再進場會造成「掛單瞬間觸發」(幣安錯誤 -2021),所以直接放棄這筆訊號,不進場。
    """
    pass


class ProtectionOrderError(Exception):
    """
    市價單已成交,但停損/停利單掛失敗。程式已經嘗試自動把倉位平掉,避免留下沒有保護的裸倉。
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

    stop_price = round_step(signal["stop_price"], price_p)
    target_price = round_step(signal["target_price"], price_p)

    # 下單前價格檢查:標記價格必須還在「停損與停利之間」,且離兩端各保留一點緩衝,
    # 否則條件單會在掛單瞬間觸發(-2021),所以先擋掉,不要讓市價單先成交了才發現
    mark_price = float(client.get_mark_price(symbol)["markPrice"])
    stop_dist = abs(signal["entry_price"] - signal["stop_price"])
    buffer = 0.05 * stop_dist
    if signal["direction"] == "long":
        price_ok = (stop_price + buffer) < mark_price < (target_price - buffer)
    else:
        price_ok = (target_price + buffer) < mark_price < (stop_price - buffer)
    if not price_ok:
        raise SignalStaleError(
            f"目前標記價 {mark_price} 已貼近或越過這筆訊號的停損 {stop_price} / 停利 {target_price},"
            f"訊號視為過期,不進場"
        )

    leverage = calc_leverage(signal["entry_price"], qty, account_balance)
    client.set_leverage(symbol, leverage)

    entry_side = "BUY" if signal["direction"] == "long" else "SELL"
    exit_side = "SELL" if signal["direction"] == "long" else "BUY"

    # 1. 市價進場
    entry_order = client.new_order(
        symbol=symbol, side=entry_side, order_type="MARKET", quantity=qty,
    )

    # 2+3. 停損單 / 停利單(觸價後市價全部平倉)
    # 注意:幣安2025年12月起,條件單(STOP_MARKET/TAKE_PROFIT_MARKET)必須改用
    # Algo Order API(new_algo_order),舊的 new_order 端點會回傳錯誤代碼 -4120
    # 若任何一張掛失敗:市價單已經成交,絕不能留下沒有保護的倉位 -> 撤掉已掛的條件單並立刻反向平倉
    try:
        stop_order = client.new_algo_order(
            symbol=symbol, side=exit_side, order_type="STOP_MARKET",
            trigger_price=stop_price, close_position=True,
        )
        tp_order = client.new_algo_order(
            symbol=symbol, side=exit_side, order_type="TAKE_PROFIT_MARKET",
            trigger_price=target_price, close_position=True,
        )
    except Exception as protect_err:
        close_msg = "已自動平倉"
        try:
            try:
                client.cancel_all_algo_open_orders(symbol)
            except Exception:
                pass
            client.new_order(
                symbol=symbol, side=exit_side, order_type="MARKET",
                quantity=qty, reduce_only=True,
            )
        except Exception as close_err:
            close_msg = f"自動平倉也失敗({close_err}),請立刻手動檢查並處理 {symbol} 倉位!"
        raise ProtectionOrderError(
            f"停損/停利單掛單失敗({protect_err});{close_msg}"
        ) from protect_err

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
