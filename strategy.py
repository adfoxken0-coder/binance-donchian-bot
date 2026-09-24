"""
Donchian突破 + EMA200濾網 + ATR停損 + 固定盈虧比策略邏輯
翻譯自 TradingView Pine Script 版本(已完成穩健性測試的最終參數)
BTC日線 / ETH 4H 共用同一套計算函數,只是套用不同參數
"""
from dataclasses import dataclass


@dataclass
class StrategyParams:
    donchian_len: int
    trend_ema: int
    vol_ma_len: int
    vol_mult: float
    atr_len: int
    atr_mult: float
    rr_ratio: float
    risk_usd: float


# 已驗證的兩組最終參數(2026/9 穩健性測試結果)
# BTC: 日線, 通道20天, ATR停損1.5倍, 獲利因子1.855
BTC_PARAMS = StrategyParams(
    donchian_len=20, trend_ema=200, vol_ma_len=20, vol_mult=1.2,
    atr_len=14, atr_mult=1.5, rr_ratio=1.5, risk_usd=10.0,
)

# ETH: 4小時, 通道35根, ATR停損2.0倍, 獲利因子1.437
ETH_PARAMS = StrategyParams(
    donchian_len=35, trend_ema=200, vol_ma_len=20, vol_mult=1.5,
    atr_len=14, atr_mult=2.0, rr_ratio=1.5, risk_usd=10.0,
)


def _ema(values, period):
    """簡單EMA實作,起始值用第一個資料點,跟Pine Script的ta.ema在資料夠長時會收斂到幾乎一致"""
    k = 2 / (period + 1)
    ema_values = [values[0]]
    for v in values[1:]:
        ema_values.append(v * k + ema_values[-1] * (1 - k))
    return ema_values


def _sma(values, period):
    result = [None] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1:i + 1]) / period
    return result


def _atr(highs, lows, closes, period):
    """Wilder's ATR,跟Pine Script的ta.atr()演算法一致"""
    trs = [None]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    atr_values = [None] * len(trs)
    if len(trs) > period:
        first_atr = sum(trs[1:period + 1]) / period
        atr_values[period] = first_atr
        for i in range(period + 1, len(trs)):
            atr_values[i] = (atr_values[i - 1] * (period - 1) + trs[i]) / period
    return atr_values


def parse_klines(raw_klines):
    """把幣安 klines API 回傳的原始資料轉成方便計算的欄位(list of list -> 分離陣列)"""
    highs, lows, closes, volumes = [], [], [], []
    for k in raw_klines:
        highs.append(float(k[2]))
        lows.append(float(k[3]))
        closes.append(float(k[4]))
        volumes.append(float(k[5]))
    return highs, lows, closes, volumes


def compute_signal(raw_klines, params: StrategyParams):
    """
    輸入:raw_klines 必須是「已收盤」的K線陣列(呼叫端要自行拿掉最後一根還在跑的K線)
    回傳:dict(有訊號)或 None(無訊號)
    {
        "direction": "long" / "short",
        "entry_price": float,
        "stop_price": float,
        "target_price": float,
        "qty": float,          # 以標的幣量計算(例如多少顆BTC/ETH)
    }
    """
    highs, lows, closes, volumes = parse_klines(raw_klines)
    n = len(closes)

    min_len = max(
        params.donchian_len + 2, params.trend_ema + 2,
        params.atr_len + 2, params.vol_ma_len + 2,
    )
    if n < min_len:
        return None

    ema_series = _ema(closes, params.trend_ema)
    vol_ma_series = _sma(volumes, params.vol_ma_len)
    atr_series = _atr(highs, lows, closes, params.atr_len)

    idx = n - 1  # 最新一根已收盤K線
    close_now = closes[idx]
    ema_now = ema_series[idx]
    vol_now = volumes[idx]
    vol_ma_now = vol_ma_series[idx]
    atr_now = atr_series[idx]

    if ema_now is None or vol_ma_now is None or atr_now is None:
        return None

    # Donchian通道:排除當根,取「前params.donchian_len根」的最高/最低(對應Pine的 [1] 位移)
    donchian_high = max(highs[idx - params.donchian_len:idx])
    donchian_low = min(lows[idx - params.donchian_len:idx])

    # 前一根的通道值,用來判斷「剛突破」(crossover/crossunder)
    prev_close = closes[idx - 1]
    prev_donchian_high = max(highs[idx - 1 - params.donchian_len:idx - 1])
    prev_donchian_low = min(lows[idx - 1 - params.donchian_len:idx - 1])

    vol_confirm = vol_now > params.vol_mult * vol_ma_now

    long_breakout = (
        prev_close <= prev_donchian_high and close_now > donchian_high
        and close_now > ema_now and vol_confirm
    )
    short_breakout = (
        prev_close >= prev_donchian_low and close_now < donchian_low
        and close_now < ema_now and vol_confirm
    )

    if long_breakout:
        stop_price = close_now - params.atr_mult * atr_now
        stop_dist = close_now - stop_price
        if stop_dist <= 0:
            return None
        return {
            "direction": "long",
            "entry_price": close_now,
            "stop_price": stop_price,
            "target_price": close_now + params.rr_ratio * stop_dist,
            "qty": params.risk_usd / stop_dist,
        }

    if short_breakout:
        stop_price = close_now + params.atr_mult * atr_now
        stop_dist = stop_price - close_now
        if stop_dist <= 0:
            return None
        return {
            "direction": "short",
            "entry_price": close_now,
            "stop_price": stop_price,
            "target_price": close_now - params.rr_ratio * stop_dist,
            "qty": params.risk_usd / stop_dist,
        }

    return None
