# BTC/ETH Donchian突破自動交易機器人

翻譯自 TradingView Pine Script 策略,已完成參數穩健性測試:
- **BTC**:日線,通道20天,ATR停損1.5倍,盈虧比1:1.5,獲利因子1.855
- **ETH**:4小時,通道35根,ATR停損2.0倍,盈虧比1:1.5,獲利因子1.437

## 檔案說明

| 檔案 | 說明 |
|---|---|
| `binance_futures_client.py` | 幣安合約API簽名請求工具,支援測試網/正式環境切換 |
| `strategy.py` | 策略邏輯核心:Donchian突破+EMA200濾網+ATR停損+固定盈虧比 |
| `order_manager.py` | 下單模組:計算槓桿、下市價單、掛停損停利單(用Algo Order API) |
| `risk_manager.py` | 風控模組:每日虧損上限(6USDT,觸發後暫停24小時) |
| `notifier.py` | Telegram通知模組:下單成功、平倉(停損/停利)、風控觸發、程式錯誤時推播 |
| `trade_tracker.py` | 交易追蹤模組:偵測平倉事件,更新累計勝敗統計 |
| `main.py` | 主執行程式,串接以上所有模組 |
| `force_test_order.py` | 強制測試工具,用假訊號驗證下單流程(只能在測試網用) |
| `risk_state.json` | 風控狀態記錄,GitHub Actions會自動commit回repo保存 |
| `position_tracker.json` | 記錄目前開倉中的倉位資訊,用來偵測平倉事件 |
| `trade_stats.json` | 累計勝敗統計(獲利單數、虧損單數、累計淨損益) |
| `.github/workflows/btc_daily.yml` | BTC日線策略的排程設定 |
| `.github/workflows/eth_4h.yml` | ETH 4H策略的排程設定 |
| `test_telegram.py` | 純粹測試Telegram通知有沒有送達,不涉及任何幣安操作 |
| `.github/workflows/test_telegram.yml` | 手動觸發,測試Telegram通知設定是否正確 |
| `.github/workflows/test_binance_order.yml` | 手動觸發,用假訊號在測試網真的下一次單,驗證整套下單流程 |

## 第一次使用前必做

### 1. 安裝套件
```bash
pip install -r requirements.txt
```

### 2. 設定環境變數(用測試網的Key,不要用正式環境的!)
```bash
export BINANCE_API_KEY="你的測試網API Key"
export BINANCE_API_SECRET="你的測試網API Secret"
export BINANCE_TESTNET="true"
```

### 3. 先用 dry-run 模式測試(不會真的下單)
```bash
python main.py --symbol BTCUSDT --interval 1d --dry-run
python main.py --symbol ETHUSDT --interval 4h --dry-run
```
這一步只會抓資料、印出有沒有訊號,絕對不會下單。先跑幾次確認:
- 程式能正常連線抓到K線資料(沒有跳出連線錯誤)
- 如果剛好遇到訊號,印出來的進場價/停損/停利/數量是否合理

### 4. 拿掉 --dry-run,在測試網真的下單測試
```bash
python main.py --symbol BTCUSDT --interval 1d
```
**只有在確認 `BINANCE_TESTNET="true"` 的情況下才這樣做**,這樣即使真的下單,用的也是虛擬USDT,不會有真實損失。

下單後,到 https://testnet.binancefuture.com 網頁上確認:
- 訂單是否正確出現
- 停損單、停利單是否都正確掛上
- 槓桿倍數是否合理(沒有出現離譜的數字)

### 5. 確認測試網穩定運作一段時間後,才考慮切換正式環境

切換方式:把環境變數改成正式環境的 API Key/Secret,並且 `BINANCE_TESTNET="false"`。

**務必謹慎**,建議:
- 先用小資金(比如原本規劃的100u)
- 持續觀察至少2-4週,確認邏輯運作跟預期一致
- 隨時可以用 `client.cancel_all_open_orders(symbol)` 緊急清空掛單

## 安全提醒

- API Key 權限只勾選「啟用合約交易」,**絕對不要開提幣權限**
- `order_manager.py` 裡的 `MAX_LEVERAGE_CAP = 20` 是安全上限,不管理論計算出多少倍,實際下單絕對不會超過這個值,可依風險承受度自行調整
- `SYMBOL_PRECISION` 目前是手動填的精度數字,如果幣安調整規則,建議改成呼叫 `client.get_exchange_info()` 動態抓取最新精度,避免下單失敗或精度錯誤
- 每日虧損上限預設 **6 USDT**,觸發後暫停交易 **24小時**,數值可在 `risk_manager.py` 開頭的 `DAILY_MAX_LOSS_USD` / `HALT_DURATION_HOURS` 調整
- 單一倉位限制是**每個交易對各自獨立**——BTC跟ETH可以同時各持有一筆倉位,但同一交易對不會重複進場

## 部署到 GitHub Actions(第6步)

### 1. 上傳檔案到你的 GitHub repo

把整個資料夾的所有檔案上傳,**保留資料夾結構**,`.github/workflows/` 這個路徑要維持不變。

### 2. 設定 GitHub Secrets

到 repo 的 **Settings → Secrets and variables → Actions**,新增以下幾組:

- `BINANCE_API_KEY`:先用測試網的 API Key 測試,確認穩定後再換成正式環境的
- `BINANCE_API_SECRET`:對應的 Secret
- `BINANCE_TESTNET`:填 `true`(測試網)或 `false`(正式環境,真金白銀,務必謹慎)
- `TELEGRAM_BOT_TOKEN`:Telegram Bot Token(可以沿用你 pionex 專案裡任一個現有的Bot,或另外建一個新的專門用來發自動交易通知,步驟跟你之前建 pionex Bot 時完全一樣)
- `TELEGRAM_CHAT_ID`:對應的 Chat ID

**如果不想設定Telegram**,兩個Secrets留空不填也沒關係,程式會自動偵測到沒有設定,改成只在執行記錄(Logs)裡印出通知內容,不會報錯中斷。

### 通知會在什麼時候推播

- ✅ **下單成功**:方向、數量、槓桿、進場價、停損停利價位
- 🎯💥 **平倉事件(停利或停損觸發)**:這筆損益、累計獲利單數/虧損單數/勝率/累計淨損益
- 🛑 **觸發每日虧損上限**:當天累計損益、暫停24小時的提醒(只在剛觸發的那一刻通知一次,暫停期間不會重複騷擾)
- ⚠️ **程式發生未預期錯誤**:方便你不用一直盯著GitHub Actions的執行記錄

沒有訊號、倉位還在跑中、或風控暫停中重複檢查時,**不會發送通知**,避免每4小時或每天都收到「沒事」的訊息轟炸。

### 平倉偵測的運作原理

因為程式靠GitHub Actions每次重新啟動執行,沒有常駐程序能即時監控訂單狀態,所以偵測平倉的方式是:**每次執行時,比對「上次記錄還有倉位在跑」跟「這次實際查詢到的持倉狀態」**。如果上次有、這次沒了,就代表這段期間被停損或停利觸發平倉,程式會去查詢那筆倉位期間的已實現損益,依正負判斷結果並更新累計統計。

這代表**平倉通知會有時間延遲**——不是觸價的當下馬上通知,而是要等到下一次排程執行時(BTC最慢等到隔天、ETH最慢等到下個4小時)才會發現並推播。如果之後想要更即時的通知,需要改用常駐監控的架構(不再是GitHub Actions排程式的),這是比較大的改動,先讓你知道目前的限制。

### 3. 排程時間

- **BTC**:每天 UTC 00:05 執行一次(對應台北時間 08:05),日線K線收盤後留5分鐘緩衝
- **ETH**:每4小時執行一次(UTC 00:05, 04:05, 08:05, 12:05, 16:05, 20:05)

兩個 workflow 都設定了 `workflow_dispatch`,可以在 Actions 頁面手動點擊 **Run workflow** 立即測試,不用等排程時間到。

### 4. 關於狀態檔案的持久化

GitHub Actions 每次執行都是全新的容器環境,程式執行完後,`risk_state.json`(風控狀態)、`position_tracker.json`(持倉追蹤)、`trade_stats.json`(累計勝敗統計)這三個檔案的更新內容,會被 workflow 自動 commit 回 repo,下次執行時 `actions/checkout` 會抓到最新版本,這樣所有狀態才能跨越不同次執行被記住。

**BTC 跟 ETH 這兩個 workflow 共用這三個狀態檔案**(每日虧損上限、累計勝敗統計都是帳戶層級的,不分交易對;`position_tracker.json` 雖然是各自交易對獨立的欄位,但存在同一個檔案裡),所以兩者的並行控制群組(`concurrency.group`)設成一樣的名稱(`trading-bot-risk-state`),確保不會同時搶著 commit 造成衝突,寧可排隊晚幾分鐘執行,也不要冒衝突風險。

### 5. 兩個手動測試 workflow(不用打開CMD就能測)

到 repo 的 **Actions** 頁面,左側會看到兩個獨立的測試用workflow,點進去、點 **Run workflow** 就能觸發:

**Test Telegram Notification**
- 純粹測試 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 這兩個Secret設定是否正確
- 不會碰任何幣安API,不會下單,執行完看Telegram有沒有收到測試訊息即可
- 這個workflow沒有寫入權限(`permissions: contents: read`),不會修改任何狀態檔案

**Test Binance Testnet Order**
- 觸發時可以選擇要測試的 **交易對**(BTCUSDT/ETHUSDT)跟**方向**(long/short)
- 用假造的訊號在測試網真的下一次單,驗證進場、槓桿計算、停損停利掛單的完整流程
- **只能在測試網用**:腳本內部強制檢查 `BINANCE_TESTNET` 這組Secret必須是 `true`,不是的話會直接報錯拒絕執行,不會因為這個workflow而放寬「不能在正式環境亂測」的安全限制
- 執行完會把 `risk_state.json` / `position_tracker.json` / `trade_stats.json` 的變化commit回repo,跟正式排程的行為一致

### 6. 測試順序建議

1. 先確認 Secrets 裡的 `BINANCE_TESTNET` 是 `true`
2. 到 Actions 頁面,手動觸發 **BTC Daily Donchian Strategy**,看執行記錄(Logs)是否正常
3. 手動觸發 **ETH 4H Donchian Strategy**,同樣確認
4. 觀察至少幾天的自動排程執行記錄,確認穩定後,才考慮把 Secrets 換成正式環境的 Key

## 之後可以擴充的方向

- 動態抓取交易對精度,取代目前手動維護的 `SYMBOL_PRECISION`
- 幣安2025年12月的Algo Order API變更後,`stop_algo_id`/`tp_algo_id` 目前只是印出來記錄,還沒有寫「查詢條件單狀態」或「手動取消」的輔助功能,之後可以加
