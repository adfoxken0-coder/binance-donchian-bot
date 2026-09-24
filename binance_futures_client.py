"""
幣安合約(Futures)API 簽名請求工具
支援正式環境跟測試網,只要切換 testnet 參數即可,程式邏輯完全共用
"""
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode


class BinanceFuturesClient:
    MAINNET_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"

    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    def _sign(self, params):
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _request(self, method, path, params=None, signed=False):
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            params["signature"] = self._sign(params)
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, params=params, timeout=15)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise
        if resp.status_code != 200:
            raise RuntimeError(f"幣安API錯誤 [{resp.status_code}]: {data}")
        return data

    # ---- 公開資料(不需簽名) ----
    def get_klines(self, symbol, interval, limit=200):
        return self._request("GET", "/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })

    def get_mark_price(self, symbol):
        return self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})

    def get_exchange_info(self):
        return self._request("GET", "/fapi/v1/exchangeInfo")

    # ---- 帳戶/交易(需簽名) ----
    def get_account_balance(self):
        return self._request("GET", "/fapi/v2/balance", signed=True)

    def get_position_risk(self, symbol=None):
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v2/positionRisk", params, signed=True)

    def set_leverage(self, symbol, leverage):
        return self._request("POST", "/fapi/v1/leverage", {
            "symbol": symbol, "leverage": leverage,
        }, signed=True)

    def new_order(self, symbol, side, order_type, quantity=None, stop_price=None,
                  close_position=False, reduce_only=False, price=None,
                  time_in_force=None, working_type="MARK_PRICE"):
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if quantity is not None:
            params["quantity"] = quantity
        if stop_price is not None:
            params["stopPrice"] = stop_price
            params["workingType"] = working_type
        if price is not None:
            params["price"] = price
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
        if close_position:
            params["closePosition"] = "true"
        if reduce_only and not close_position:
            params["reduceOnly"] = "true"
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def cancel_all_open_orders(self, symbol):
        return self._request("DELETE", "/fapi/v1/allOpenOrders", {
            "symbol": symbol,
        }, signed=True)

    # ---- 條件單(Algo Order,幣安2025/12起強制改用這個端點) ----
    def new_algo_order(self, symbol, side, order_type, trigger_price,
                        quantity=None, close_position=False, working_type="MARK_PRICE"):
        """
        用來下 STOP_MARKET / TAKE_PROFIT_MARKET 這類條件單。
        幣安2025年12月的API變更後,這些訂單類型必須透過此端點下單,
        舊的 /fapi/v1/order 會回傳錯誤代碼 -4120。
        """
        params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": trigger_price,
            "workingType": working_type,
        }
        if close_position:
            params["closePosition"] = "true"
        elif quantity is not None:
            params["quantity"] = quantity
        return self._request("POST", "/fapi/v1/algoOrder", params, signed=True)

    def cancel_all_algo_open_orders(self, symbol):
        return self._request("DELETE", "/fapi/v1/algoOpenOrders", {
            "symbol": symbol,
        }, signed=True)

    # ---- 損益歷史(用於每日虧損風控計算、單筆交易勝敗判斷) ----
    def get_income_history(self, start_time=None, symbol=None, limit=1000):
        """
        取得損益歷史紀錄,包含已實現盈虧(REALIZED_PNL)、手續費(COMMISSION)、
        資金費率(FUNDING_FEE)等,總和即為某段時間內的真實淨損益。
        symbol 可選填,篩選只看單一交易對(用於判斷單筆交易是贏是輸)。
        """
        params = {"limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if symbol is not None:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v1/income", params, signed=True)
