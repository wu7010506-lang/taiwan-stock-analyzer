# TWSE 收盤行情延遲：替代資料來源與備援架構

研究日期：2026-08-11  
範圍：台股 TWSE／TPEx；目標是解決 TWSE `STOCK_DAY_ALL` 收盤後仍停留在前一交易日，導致排行榜無法發布。  
資料原則：只採官方文件、官方 API、官方 SDK／GitHub。未找到官方承諾的部分，明確標示為未知或推論。

## 結論先行

有替代方法，而且不必等 `STOCK_DAY_ALL` 完成換日。最可行的做法是：

1. **若可接受月費，首選 Fugle MarketData 開發者方案**：用兩個全市場快照請求分別取得 TSE、OTC，官方文件標示快照每 5 秒更新；開發者方案為 NT$1,499/月、快照 600 次/分。它最容易直接接進現有 FastAPI 資料管線。
2. **若已有或願意開玉山證券戶，首選玉山行情 API 作低成本主源**：有 TSE、OTC 全市場快照，開發者權限可免費取得，快照 600 次/分；但它與 Fugle 都由時報資訊／群馥技術鏈提供，兩者不是適合互相驗證的獨立雙源。
3. **若已有永豐證券戶，Shioaji 很適合當獨立備援**：盤後 `snapshots` 每次最多 500 檔，上市櫃約 4～5 批即可抓完；官方限制是行情查詢合計 50 次／10 秒，沒有近 30 日 API 成交者每日流量仍有 500 MB。
4. **若重視交易所原始資料與正式授權，TWSE Data E-Shop 是最可靠的 TWSE 盤後主源／稽核源**：每日收盤行情檔約於 14:00、15:30、17:30 產製，內部使用 NT$1,000/月；TPEx 仍需另外接來源。
5. **FinMind 保留作歷史回補或第三備援，不要承擔「收盤後準時發布」責任**：官方文件有日價量 API 與每小時額度，但沒有承諾每日資料完成時間，且明示不保證時效性。
6. **TWSE MIS 只用於人工或小樣本核對，不建議當自動化主源**：它是官方免費瀏覽的 5 秒行情網站，但 `getStockInfo.jsp` 並不是公開承諾、具版本與 SLA 的批次 API；交易資訊再傳輸／加值另有授權要求。

因此，推薦的實務組合是：

- 有預算：**Fugle 全市場快照（當日發布）→ Shioaji 或官方盤後檔抽查 → TWSE/TPEx OpenAPI 隔夜回補與對帳**。
- 無月費、已有券商帳戶：**玉山行情 API 或 Shioaji（當日發布）→ 官方 OpenAPI 隔夜回補與對帳**。
- 要最正式的原始資料：**TWSE Data E-Shop（TWSE）＋ TPEx 官方來源 → 券商／Fugle 作故障備援**。

## 來源比較

| 來源 | 更新時效 | TWSE／TPEx 覆蓋 | 歷史／盤中能力 | 授權、費用與限制 | 建議角色 |
|---|---|---|---|---|---|
| TWSE OpenAPI `STOCK_DAY_ALL` | 每日，但官方資料集只標示「每 1 日」，沒有保證完成時刻 | TWSE；TPEx 要接 TPEx OpenAPI | 盤後當日整批；非即時 | 免費，政府資料開放授權；本次問題正是換日可能延遲 | 最終官方回補／對帳，不再當唯一準時發布來源 |
| TWSE 其他免費盤後端點 | 端點用途不同，沒有證據顯示更新更快 | 主要 TWSE | `STOCK_DAY_AVG_ALL` 只有收盤與月均；`MI_INDEX` 是大盤統計；個股月查詢是逐檔 | 免費；仍屬 TWSE 同一資料鏈 | 不算真正備援，也無法完整替代 OHLCV |
| TWSE MIS 基本市況報導 | 官方說明盤中提供即時資訊及 5 秒行情快照 | 官方網站涵蓋市場與個股；上櫃另有 TPEx MIS | 盤中成交、五檔與收盤前揭示；不是歷史資料庫 | 免費瀏覽；交易資訊權利屬 TWSE，傳輸、傳播或供第三人使用須取得同意；未見公開批次 API／SLA | 人工或小樣本核對；不作自動化全市場主源 |
| TWSE Data E-Shop「每日收盤行情」 | 官方列出約 14:00、15:30、17:30 各產製一次 | TWSE | 每日正式收盤檔與歷史訂購 | 內部使用 NT$1,000/月，外部使用 NT$1,500/月；商品頁列線上下載／Email，平台亦說明可依商品用 API／URL 傳遞，串接方式應先向 TWSE 確認 | 最正式的 TWSE 主源／稽核源 |
| Fugle MarketData | 全市場快照官方標示每 5 秒更新 | TSE、OTC，亦支援 ESB／TIB／PSB | 日內、快照、WebSocket、歷史行情 | 開發者 NT$1,499/月：快照與日內 600/min、WebSocket 300 訂閱／2 連線；進階 NT$2,999/月；資料成交量、成交值不含零股及鉅額交易，且不得任意轉接／再散布 | 最容易落地的全市場當日主源 |
| 玉山行情 API | 即時 WebSocket；REST 有日內與全市場快照 | `TSE`、`OTC`，也有 ESB／TIB／PSB | 日內、快照、歷史；日 K 單次最多 1 年、個股可回溯至 2010 年；分 K 近五日 | 玉山帳戶可免費使用基本權限，完成事前準備可免費取得開發者權限；日內與快照 600/min，WebSocket 300 訂閱／2 連線，歷史 60/min；成交量值同樣不含零股與鉅額 | 免費主源候選；但與 Fugle 是相關供應鏈，不可把兩者視為獨立驗證 |
| 永豐 Shioaji | 即時訂閱由交易所行情轉送；盤後快照可直接取得當日 OHLCV | 合約與快照支援 `TSE`、`OTC` | 即時 Tick／BidAsk；Snapshots、Ticks、Kbars；Kbars 單次日期區間最多 30 日 | 需永豐 API Key（推論上需永豐證券帳戶）；snapshot 每次最多 500 檔；行情查詢合計 50 次／10 秒；無近 30 日 API 成交者每日 500 MB；即時訂閱最多 200 檔 | 很好的獨立盤後備援；不適合用 200 訂閱做全市場即時串流 |
| FinMind `TaiwanStockPrice` | 有台股日價量 API，但官方未承諾每日完成時間 | 台股資料集；實際市場範圍應以 `TaiwanStockInfo`／回傳值驗證 | 歷史日價量、調整價、Tick／分 K 等依方案開放 | 目前官方快速開始標示：無 token 300/hour、有 token 600/hour；條款不保證正確性、完整性或時效性，也限制即時資料直接對外呈現 | 歷史回補、研究與第三備援；不作收盤準時發布主源 |

## 各來源的證據與判斷

### 1. TWSE／TPEx 免費 OpenAPI：同源端點不是獨立備援

TWSE 的官方 Swagger 列出 `STOCK_DAY_ALL`、`STOCK_DAY_AVG_ALL`、`MI_INDEX` 等端點。政府資料開放平臺將「上市個股日成交資訊」標示為每日更新、免費並採政府資料開放授權，但沒有公布每天確切完成時間或 SLA。

- [TWSE OpenAPI Swagger](https://openapi.twse.com.tw/)
- [政府資料開放平臺：上市個股日成交資訊](https://data.gov.tw/dataset/11549)
- [TWSE 個股日成交資訊查詢](https://www.twse.com.tw/zh/trading/historical/stock-day.html)
- [TPEx OpenAPI Swagger](https://www.tpex.org.tw/openapi/)

`STOCK_DAY_AVG_ALL` 不能替代完整 OHLCV；`MI_INDEX` 是大盤統計；逐檔的 `STOCK_DAY` 月查詢即使偶爾較早出現當日資料，也沒有官方保證更新先後，而且仍屬 TWSE 同一資料鏈。用它們取代 `STOCK_DAY_ALL` 只能算同源降級，不是可靠故障切換。

### 2. TWSE MIS：速度快，但不是公開支援的後端批次 API

TWSE 官方說明 MIS 提供即時盤中指數、成交價與最佳五檔價量；交易制度頁說明盤中提供即時資訊與 5 秒行情快照。資訊服務問答同時說明，MIS 交易資訊免費供各界「瀏覽」，但交易資訊智慧財產權屬 TWSE，若加值後傳輸、傳播或供他人使用，須取得 TWSE 同意並簽約。

- [TWSE 投資指南：MIS 功能](https://www.twse.com.tw/zh/about/company/guide.html)
- [TWSE 集中市場交易制度：5 秒行情快照](https://www.twse.com.tw/zh/products/system/trading.html)
- [TWSE 資訊服務問答：免費瀏覽與再利用授權](https://wwwc.twse.com.tw/zh/products/information/qa.html)
- [TWSE 即時交易資訊申請](https://www.twse.com.tw/zh/products/information/real-time.html)
- [TPEx 基本市況報導](https://mis.tpex.org.tw/)

網路上常見的 `mis.twse.com.tw/stock/api/getStockInfo.jsp` 是 MIS 網頁內部使用方式，但沒有在上述官方文件中被承諾為公開版本化 API，也沒有官方批次大小、速率與可用率 SLA。故不應用大量批次輪詢建立全市場資料庫；最多作少量候選的日期、收盤價抽查。

### 3. TWSE Data E-Shop：明確產製時間的正式官方方案

「每日收盤行情」商品頁明確列出約於每交易日 14:00、15:30、17:30 各產製一次，內容包含證券代號、OHLC、成交股數、成交筆數、成交金額與最後買賣價等。內部使用 NT$1,000/月，外部使用 NT$1,500/月。這是本次調查中，唯一能由 TWSE 官方頁面直接確認產製時間的 TWSE 收盤來源。

- [TWSE Data E-Shop：每日收盤行情](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8)
- [TWSE Data E-Shop 首頁與傳遞方式](https://eshop.twse.com.tw/zh/home/index)
- [TWSE 資訊服務分類](https://wwwc.twse.com.tw/zh/products/information/information.html)

限制是只解決 TWSE；TPEx 仍需使用 TPEx 官方來源或同一個第三方全市場供應商。若網站只供本人本機使用，「內部使用」看似符合，但最終仍應以訂購條款及 TWSE 回覆為準。

### 4. Fugle MarketData：兩次請求就能取得 TSE／OTC 全市場快照

Fugle 官方文件說明即時行情源自 TWSE、TPEx、TAIFEX；`GET /snapshot/quotes/{market}` 可依 `TSE`、`OTC` 取得整個市場的快照，系統每 5 秒更新。回傳包含日期、時間、代號、OHLC、成交量、成交金額與最後更新時間。

- [Fugle 行情 API 簡介與使用規範](https://developer.fugle.tw/docs/data/intro/)
- [Fugle 全市場 Snapshot Quotes](https://developer.fugle.tw/docs/data/http-api/snapshot/quotes/)
- [Fugle 行情方案與價格](https://developer.fugle.tw/docs/pricing/)
- [Fugle 官方 Python SDK](https://github.com/fugle-dev/fugle-marketdata-python)

對排行榜最重要的優點是：同一個供應商能以相同時間戳、相同欄位定義取得 TSE 與 OTC，不必混用 8/11 TPEx 與 8/10 TWSE。開發者方案的全市場快照 600/min 已遠高於每日收盤同步需求。

重要限制：官方明示成交量與成交值不含零股及鉅額交易，且不得任意轉接、轉售或再授權。因此若現有 20 日均量來自包含零股／鉅額的官方盤後資料，不能毫無標記地把 Fugle 的當日量接在後面計算量比。

### 5. 玉山行情 API：免費的 Fugle 技術鏈方案

玉山官方文件提供 TSE、OTC 全市場 `snapshot/quotes/{market}`，另有日內 REST、WebSocket 與歷史 K 線。玉山帳戶免費享有基本權限，完成事前準備可免費取得開發者權限；開發者級限制為日內 600/min、快照 600/min、WebSocket 300 訂閱／2 連線、歷史 60/min。

- [玉山行情 API 簡介](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/intro/)
- [玉山全市場 Snapshot Quotes](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/http-api/snapshot/quotes/)
- [玉山行情 API 速率限制](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/rate-limit/)
- [玉山 API 常見問答：帳戶與免費權限](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/faq/intro/)
- [玉山歷史行情](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/http-api/historical/candles/)

玉山文件明載 Web API 數據由時報資訊與群馥科技提供，且玉山行情 API 由 Fugle 技術團隊開發。因此它能避開 TWSE OpenAPI 的發布延遲，卻不宜和 Fugle 互相當「獨立」校驗源；兩者可能同時受同一供應鏈事故影響。

### 6. 永豐 Shioaji：盤後 4～5 批即可抓完整市場

Shioaji 官方市場快照包含 OHLC、成交量、成交額與時間戳，每次最多 500 檔。行情查詢合計限制為 50 次／10 秒；沒有近 30 日 API 成交者每日流量限制仍有 500 MB。即時訂閱最多 200 檔，故適合「排行榜前十＋當前個股」盤中追蹤，或盤後分批快照，不適合用訂閱覆蓋全市場。

- [Shioaji 市場快照：每次最多 500 檔](https://sinotrade.github.io/zh/tutor/market_data/snapshot/)
- [Shioaji 使用限制](https://sinotrade.github.io/zh/tutor/limit/)
- [Shioaji 即時證券行情](https://sinotrade.github.io/zh/tutor/market_data/streaming/stocks/)
- [Shioaji 歷史行情](https://sinotrade.github.io/zh/tutor/market_data/historical/)
- [Shioaji API Key 申請](https://sinotrade.github.io/zh/tutor/prepare/token/)
- [Shioaji 官方 GitHub](https://github.com/Sinotrade/Shioaji)

以約 2,000 檔上市櫃股票估算，分成不超過 500 檔的 4～5 批即可完成；這是根據官方單批上限與市場規模做的工程推論，不是永豐承諾的全市場完成時間。程式仍須逐批檢查回傳日期、時間與覆蓋率。

### 7. FinMind：適合歷史與補洞，不適合作收盤 SLA

FinMind 官方文件提供 `TaiwanStockPrice`、調整價與其他台股資料集；目前快速開始頁標示無 token 300/hour、有 token 600/hour。條款則明確寫明不對資料正確性、完整性、時效性與更新延誤負責，並限制即時資料直接呈現在對外 Web／App。

- [FinMind 快速開始與速率限制](https://finmind.github.io/en/quickstart/)
- [FinMind 台股技術面／日價量資料集](https://finmind.github.io/tutor/TaiwanMarket/Technical/)
- [FinMind 使用條款](https://finmind.github.io/PrivacyPolicy/)
- [FinMind 免責與資料授權](https://finmind.github.io/Disclaimer/)

它可以補歷史財價量、在官方端點故障時交叉查某些標的，但沒有官方依據可保證每天 13:30、14:00 或 15:30 前完成全市場換日，不能單獨解決目前的「準時產榜」需求。

## 建議系統架構

### A. 發布源與對帳源分開

把資料分為兩個角色：

- **發布源**：能在固定時間取得同一交易日、同一來源的 TSE＋OTC 全市場快照。建議 Fugle、玉山行情 API；Shioaji 為備援。
- **對帳源**：TWSE／TPEx OpenAPI 或 TWSE Data E-Shop。稍晚取得後覆核與補寫正式盤後數據，但不得悄悄覆寫已發布榜單。

這比「永遠等唯一官方 OpenAPI」更快，也比「哪一檔缺就任意找另一個網站補」更可驗證。

### B. 收盤流程

建議流程如下：

1. 13:35～13:40 向同一發布源抓 TSE 與 OTC 全市場快照。
2. 驗證兩市場 `date` 相同、時間不早於一般交易收盤，且普通股候選同日覆蓋率各自至少 95%。
3. 只允許**整批同源**：不能部分股票用 Fugle、部分用 TWSE OpenAPI，也不宜 TSE 用 A、OTC 用 B 後直接排名。
4. 保存原始回應摘要、來源名稱、擷取時間、資料時間、列數、雜湊與欄位口徑。
5. 通過 gate 後才產生不可覆寫的當日排行榜；若失敗，沿用上一份有效榜單並顯示原因。
6. 15:30、17:30 或隔夜取得官方盤後資料後對帳；若價格、日期或列數異常，記錄 correction，不回頭竄改已發布快照。

### C. 成交量口徑不能混用

Fugle 與玉山官方都聲明其成交量、成交值不含零股與鉅額；TWSE 個股日成交資訊則說明當日統計包含一般、零股、盤後定價、鉅額交易。這會直接影響「今日量／5 日或 20 日均量」、突破量能與流動性排序。

可執行規則：

- 每筆 OHLCV 儲存 `source`、`volume_scope`、`captured_at`。
- 同一個量比的分子、分母必須來自相同 `volume_scope`。
- 若發布源改為 Fugle／玉山，至少先從該供應商重建足夠的 20～60 日成交量歷史；尚未完成前，量能分數標示不可比，而不是硬接官方歷史量。
- 價格 OHLC 可另做逐 tick 容忍度核對；成交量不能要求不同口徑來源完全相等。

### D. 來源健康與故障切換

為每個來源維護：

- 成功率、延遲、最新資料日、TSE／OTC 覆蓋率、重複列、空值率。
- 20～50 檔高流動性抽樣的 OHLC 差異。
- 連續失敗次數、429／授權錯誤、上次成功時間。
- `primary → backup → hold_previous` 的明確狀態機；不得在同一榜單逐檔靜默換源。

建議優先序：

1. Fugle 或玉山全市場快照。
2. Shioaji 分批 snapshots。
3. 若兩者皆失敗，沿用上一份有效榜單。
4. MIS 只供人工診斷；FinMind 只供歷史補洞／第三核對。
5. 官方 OpenAPI／Data E-Shop 稍後完成正式對帳。

## 不建議的方案

- **不停重試 `STOCK_DAY_ALL`**：只是增加請求，不能解決上游尚未發布。
- **改抓 `STOCK_DAY_AVG_ALL` 或 `MI_INDEX` 就當完整行情**：欄位不足，無法還原排行榜所需 OHLCV。
- **大量輪詢 MIS 內部端點**：沒有公開 API 契約／SLA，且再利用授權風險高。
- **從 Goodinfo 爬資料**：本研究未找到可供此專案合法、穩定自動化使用的官方 API 或授權文件；也不是交易所／券商一手行情源，因此不列入候選。
- **逐檔混用不同來源補空值**：可能同時混入不同時間、成交量口徑與還原規則，排行榜看似完整，實際不可重現。
- **把 Fugle 與玉山當獨立雙源**：兩者官方文件顯示供應鏈相關，應另搭 Shioaji 或交易所官方檔校驗。

## 對本專案的落地建議

最小風險、最高效益的下一步：

1. 先確認使用者是否已有玉山或永豐證券帳戶。
2. 若有玉山帳戶，先做玉山全市場快照 adapter；若沒有但可接受 NT$1,499/月，做 Fugle adapter；若有永豐帳戶，另做 Shioaji backup adapter。
3. 新增統一介面：`fetch_market_snapshot(market, as_of) -> rows + provenance`。
4. 在寫入 `daily_prices` 前做欄位映射與 `volume_scope` 分流，不覆蓋其他來源原始值。
5. 排行榜發布只讀一個已驗證的「同源市場批次」，保留現有 95% 覆蓋 gate 與上一有效榜單機制。
6. 先以 5～10 個交易日紙上並行，記錄新源相對官方最終資料的日期延遲、OHLC 差異、量值差異與榜單周轉，再決定正式主源。

若只選一個方案，我會選：**Fugle／玉山全市場快照負責當日快速產榜，TWSE／TPEx 官方資料負責稍後校正與研究資料庫；Shioaji 作真正不同供應鏈的備援。**

