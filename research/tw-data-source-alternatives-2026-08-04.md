# FinMind 以外的台股資料來源盤點

研究日期：2026-08-04。範圍限 TWSE／TPEx；目標是補歷史日價量、財報／現金流與月營收，並保留可追溯的原始資料來源。以下把「資料權威性」和「程式取得便利性」分開看：GitHub 專案大多只是擷取器，不能取代官方資料來源。

## 結論

|資料類型|正式來源（建議）|備援來源|不宜作正式依據的來源|
|---|---|---|---|
|上市日 OHLCV|TWSE 個股日成交歷史查詢|TWSE OpenAPI（僅確認當日型端點，歷史覆蓋須實測）|Yahoo／GitHub 整理 CSV|
|上櫃日 OHLCV|TPEx 個股日成交／OpenAPI|TPEx EOD 產品 API（須先確認使用條款）|第三方轉售 API|
|財報、現金流、月營收|MOPS 公開資訊觀測站|無同等權威備援；可用原始 PDF／XBRL 重抓|GitHub 爬蟲輸出、聚合站|

因此，**不應為了補齊而降低 vNext 的年限資格，也不應用第三方資料填補 MOPS 缺的財務事實**。正確方向是：官方來源可取就回補、每筆保留來源 URL／下載時間／報表期間／雜湊，仍無資料才維持「資料不足」。金融業則應另訂資格規則，不能把製造業現金流欄位硬套。

## 1. 官方來源

### TWSE：上市日價量

- [個股日成交資訊官方頁](https://www.twse.com.tw/zh/trading/historical/stock-day.html)提供歷史個股日成交查詢，頁面說明資料自 2010-01-04 起、單位為元／股；適合作為上市股票三年價量的主要回補來源。
- 常見 JSON 查詢格式為 `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=YYYYMMDD&stockNo=2330`，一次是一檔、一個月；新版路徑與回應欄位需在程式以合約測試監控。
- [TWSE OpenAPI Swagger](https://openapi.twse.com.tw/)列有 `exchangeReport/STOCK_DAY_ALL`、`exchangeReport/MI_INDEX`。目前公開描述偏向當日資料，未見可保證全歷史的參數契約；可作當日交叉驗證或備援，不應未驗證就當成完整歷史資料庫。
- **307 處理：**TWSE 網站會在 `www`／`wwwc` 等官方網域間轉址。HTTP 用戶端必須 `allow_redirects=True`，限制最終主機為 `*.twse.com.tw`，並把原 URL、最終 URL、HTTP 狀態與內容雜湊寫入失敗／成功紀錄。307 只代表請求位置改變，不能標記成資料不存在。

### TPEx：上櫃日價量

- [TPEx FAQ](https://www.tpex.org.tw/zh-tw/about/company/faq.html)指向「上櫃 > 交易資訊 > 盤後資訊 > 個股日成交資訊」，確認官方可查歷史股價。
- [TPEx OpenAPI](https://www.tpex.org.tw/openapi/)及其 [Swagger](https://www.tpex.org.tw/openapi/swagger.json)列出 `tpex_mainboard_daily_close_quotes`、`tpex_mainboard_quotes` 等資料集，適合作為上櫃日價量的結構化來源；導入前應逐月抽樣檢查欄位、停牌與除權息表現。
- 舊版月查詢範例：`https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=114/08&stkno=6488`。官方網站路徑／格式可能調整，實作要有 schema 驗證和退避重試。
- [TPEx EOD API 產品頁](https://eshop.tpex.org.tw/zh/product/detail/2c92e01394fcf4c7019518bbf65f000a)說明可訂閱上月以前歷史資料，標示價格 0/月但須申購並受條款約束；若開放 API 的可用性優於網頁端點，可作正式官方備援，先完成條款與使用量確認。

### MOPS：財報、現金流、月營收

- [MOPS 公開資訊觀測站](https://mops.twse.com.tw/mops/web/t05st48_q1)是發行公司法定揭露入口，提供資產負債表、綜合損益表、權益變動表、現金流量表、財務報告公告／書與月營業收入。
- MOPS 對此用途是**唯一可作正式依據的來源**；它是表單／PDF／XBRL 公開平台，並非有穩定版本承諾的 REST API。回補器應下載並保存原始檔或原始回應，記錄公司、報表期、公告日、URL、取得時間、SHA-256、解析版本；解析失敗不可改填 0 或沿用下一期資料。
- 月營收資料的資料新鮮度要依公告截止日判定（通常次月 10 日前），不能在月初便把上月資料視為逾期。

## 2. GitHub／程式工具：可重用但不是資料權威

|工具|資料與涵蓋|適合用途|限制與判定|
|---|---|---|---|
|[mlouielu/twstock](https://github.com/mlouielu/twstock)|直接使用 TWSE、TPEx；文件顯示會依上市／上櫃選 fetcher，月別抓取 OHLCV|作為官方日價量的程式實作參考／備援 adapter|README 警示 TWSE 約每 5 秒 3 requests；僅處理價量，不可取代財報來源|
|[voidful/tw_stocker](https://github.com/voidful/tw_stocker)|按代號 CSV 的 OHLCV、`manifest.json` 含範圍與 SHA-256|離線研究、資料缺口比對、測試 fixture|作者明示資料可能延遲、缺漏、來源修正或格式差異；不適合正式交易判斷的唯一來源|
|[pyang2045/twsemcp](https://github.com/pyang2045/twsemcp)|把 TWSE API 封裝為日價量、月營收、財報查詢工具|檢視官方端點與欄位對應的參考|第三方 MCP 封裝；需直接驗證它呼叫的官方 URL 與資料期間，不能把它當第二資料商|
|[VincentLiu3/TWSE](https://github.com/VincentLiu3/TWSE)|TWSE／OTC API 範例|舊端點和解析容錯的參考|專案年代較久，端點、格式與維護狀態均需重驗證|

`twstock` 的 [官方文件](https://twstock.readthedocs.io/zh-tw/latest/reference/stock.html)也確認其 `TWSEFetcher`／`TPEXFetcher` 按月抓取歷史資料。這有助於實作，但來源仍是交易所，故應遵守交易所速率限制、做好快取與失敗重試。

## 3. 建議的取得順序與資料品質規則

1. **日價量：**依市場分流，TWSE／TPEx 官方月資料逐月抓取；HTTP 跟隨官方 307/308；完成後以日期連續性、OHLC 合理性、成交量非負、複權／除權息欄位規則檢查。
2. **財報與現金流：**MOPS 原始 PDF／XBRL／表格優先；每期以公告日作 point-in-time 可得日，不以報表期末冒充可得日。
3. **月營收：**MOPS 原始月營收公告；保存公告日與資料月，依申報截止日評估新鮮度。
4. **交叉驗證：**FinMind 恢復時只作交叉比對（列數、最後日期、OHLCV、報表主要欄位），差異留下事件紀錄，不靜默覆蓋官方值。
5. **GitHub 資料集：**只用於離線研究或找出缺口；不得以它補出「正式候選」所需的法定財報／現金流。

## 4. 不建議的做法

- 不因 FinMind 配額耗盡就把 yfinance、免費轉售 API 或 GitHub CSV 當成財務資料正式來源。
- 不把 HTTP 307、429、HTML 欄位變更或空資料回應混為「公司沒有資料」；四者要分別記錄與重試。
- 不對上市未滿五年或未公告足夠期數的公司補分。資料不足是模型輸出的一部分。
- 不以回測表現為理由臨時降低 vNext 門檻；若要涵蓋金融業，另立金融業資料與品質門檻，再做獨立驗證。
