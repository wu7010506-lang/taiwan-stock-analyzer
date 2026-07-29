# GitHub 股票專案研究與可套用建議

> 研究日期：2026-07-29  
> 範圍：只檢視專案擁有者在 GitHub 發布的 README、原始碼結構、授權與文件；本文件是產品研究，不代表任何標的推薦或投資保證。

## 結論與優先順序

本專案最值得借鑑的不是再新增一套技術指標，而是把既有的「資料不足透明化、建議部位、Walk-forward 回測」做成可驗證的資料與投資組合流程。

| 優先 | 可套用內容 | 預期價值 | 建議方式 |
| --- | --- | --- | --- |
| P0 | 每張資料表的可驗證覆蓋率、來源、雜湊與失敗原因 | 直接解決同步不完整卻誤用模型的風險 | 自行實作 manifest / quality check，不搬資料集 |
| P0 | FinMind 配額感知的工作佇列、快取與來源切換 | 降低 public API 限流造成的資料缺口 | 改善既有同步器；Token 僅放環境變數 |
| P0 | 回測績效報表：基準、回撤、換手、成本、樣本外 | 讓「有賺」變成可審核的結果 | 先以本機日報表／HTML 匯出實作 |
| P1 | 從推薦名單到投資組合的總風險／產業／單檔上限 | 讓 5% 單檔建議不會加總成過度集中 | 自行實作限制式配置，之後再評估套件 |
| P1 | 多次參數／市場狀態的 Walk-forward 穩健性矩陣 | 防止只挑到一段漂亮的回測 | 對 vNext 建立時間點可重算的資料快照 |
| P1 | 觀察股觸發式提醒與每日決策變更紀錄 | 使用者知道「何時、為何」改變，而非只看到今日分數 | 先做站內通知與決策 diff |
| P2 | K 線疊加法人、融資融券、股利事件 | 強化個股研究脈絡 | 使用既有資料，避免把簡化技術訊號當買賣保證 |

## 可借鑑專案與具體做法

### 1. FinMind/FinMind：台股資料適配器與配額感知同步

- 專案：[FinMind/FinMind](https://github.com/FinMind/FinMind)；授權標示為 Apache-2.0，但 README 另說明其資料內容屬教育、非商業用途，實作前須同時審閱 [LICENSE](https://github.com/FinMind/FinMind/blob/master/LICENSE) 與資料服務條款。
- README 列出日價量、即時／tick、估值、三表、月營收、股利／除權息、法人、股權分散、融資券與新聞等台股資料類型，且資料每日更新；這與本專案的資料模型高度重疊。[來源](https://github.com/FinMind/FinMind#這是什麼)
- README 明示匿名 API 為每小時 300 次、帶 token 為每小時 600 次，並有週日維護時段。[來源](https://github.com/FinMind/FinMind#note)

**可套用：**

1. 將同步工作改成「資料集 × 股票 × 日期區間」的持久佇列，記錄 `attempt_count`、`next_retry_at`、HTTP／配額錯誤、最後成功日期與來源。
2. 同一交易日只取一次全市場共用資料（如法人、指數），個股資料以缺口區間補抓；遇到 429／quota 則進入冷卻時間，不無限重試。
3. `FINMIND_TOKEN` 只從環境變數讀取，頁面只顯示「已設定／未設定」與可用資料新鮮度，絕不回傳 token。

**適配與風險：**適配度最高；但不可把 public API 當成保證即時或永久完整的唯一來源，且部署公開網站前須確認資料授權與用量條件。

### 2. pyang2045/twsemcp：官方 TWSE OpenAPI 的備援與市場名單快照

- 專案：[pyang2045/twsemcp](https://github.com/pyang2045/twsemcp)，MIT 授權。[來源](https://github.com/pyang2045/twsemcp/blob/main/LICENSE)
- README 是 [TWSE OpenAPI](https://openapi.twse.com.tw/) 的 Python 封裝，涵蓋指數、交易日曆、融資券、股權資訊與上市相關資料；README 也記錄來源可能有限流、延遲約 15 至 20 分鐘與大查詢筆數上限。[來源](https://github.com/pyang2045/twsemcp#readme)

**可套用：**以交易所官方來源建立備援 adapter，並每日保存「當日上市櫃股票池」快照（上市、下市、暫停交易、產業）。這可讓回測依歷史當時可投資股票池運作，逐步降低存活者偏誤；交易日曆也可避免在非交易日誤報「資料落後」。

**適配與風險：**資料來源層非常有價值，但此專案較小、來源有延遲／筆數限制；應自建 adapter 與契約測試，不把第三方封裝當成單點依賴。

### 3. voidful/tw_stocker：資料 manifest 與完整性驗證

- 專案：[voidful/tw_stocker](https://github.com/voidful/tw_stocker)；README 未宣告授權，故只借鑑設計，不複製程式碼或資料。
- 專案將每檔 OHLCV 存為 CSV，`manifest.json` 記錄欄位、時間範圍、筆數、檔案大小與 SHA-256；`build_catalog.py --check` 驗證檔名、結構、首末列、筆數與雜湊，且不修改資料。[來源](https://github.com/voidful/tw_stocker#內容)

**可套用：**為 SQLite 資料建立 `data_quality_snapshot`：每個資料集記錄市場、應有／實有股票數、最新交易日、最早日、缺口數、來源、同步批次與檢查結果。增加唯讀的「驗證資料」工作，檢查 OHLC 合理性、日期連續性、重複列、法人買賣欄位與財報期別。

**適配與風險：**極適合處理目前覆蓋率問題；雜湊不是資料正確性的證明，仍需跨來源比對、容許更正與保留來源版本。

### 4. mlouielu/twstock：交易所節流與技術訊號隔離

- 專案：[mlouielu/twstock](https://github.com/mlouielu/twstock)，MIT 授權。[來源](https://github.com/mlouielu/twstock/blob/dev/LICENSE)
- 專案直接採用 TWSE、TPEx 資料，README 特別警告 TWSE 約為每 5 秒 3 個請求，超過可能被封鎖；它也把「四大買賣點」做成獨立函式。[來源](https://github.com/mlouielu/twstock#twstock-台灣股市股票價格擷取)

**可套用：**

1. 所有 TWSE／TPEx adapter 共用節流器（令牌桶、來源級併發上限、指數退避），不可由各 endpoint 各自發請求。
2. 將任何短線技術規則保留為「訊號解釋層」，不直接覆蓋 vNext 的企業品質、估值與市場風控結論；頁面清楚顯示它只是輔助。

**適配與風險：**節流設計應立即採用；不建議直接採用四大買賣點作自動下單或作為長線品質分數，因其規則過度簡化且未驗證台股樣本外績效。

### 5. microsoft/qlib：資料健康檢查與可重現的研究帳本

- 專案：[microsoft/qlib](https://github.com/microsoft/qlib)，MIT 授權。[來源](https://github.com/microsoft/qlib/blob/main/LICENSE)
- README 採資料、模型、策略與執行模組分離，並列出 point-in-time database、資料健康檢查、每日更新與記錄回測／評估工作流程。[來源](https://github.com/microsoft/qlib#readme)

**可套用：**不直接導入大型框架，而是採其可追溯原則：每次推薦與回測存 `model_version`、參數、股票池快照、資料截止日／雜湊、排除清單、成本假設與輸出。再加入資料健康檢查：缺失觀測、價格／成交量異常跳變、來源新鮮度與覆蓋率。

**適配與風險：**架構思想適合本專案；Qlib 自帶資料並非台股，且其 README 對第三方資料品質有提醒，不能拿來取代台股資料來源。

### 6. ranaroussi/quantstats：回測結果的風險報告與可匯出稽核

- 專案：[ranaroussi/quantstats](https://github.com/ranaroussi/quantstats)，Apache-2.0 授權。[來源](https://github.com/ranaroussi/quantstats/blob/main/LICENSE.txt)
- README 將功能分為績效統計、圖表與可產生 HTML tear sheet 的報告；列出 Sharpe、勝率、波動、回撤、月報酬、CVaR、曝險等指標，也提供 Monte Carlo 分析。[來源](https://github.com/ranaroussi/quantstats#quantstats-portfolio-analytics-for-quants)

**可套用：**研究型與 vNext 回測每次都輸出不可變更的 run ID 報告：資料截止日、股票池、排除名單、訊號日、成交日、成本、基準、月／日淨值、換手率、最大回撤、樣本外結果。先在本機產出 HTML／CSV，並從 UI 連結該次報告。

**適配與風險：**適合補足模型成績頁；匯出的是計算結果，不會自動排除存活者偏誤、未來函數或錯誤 corporate action，這些仍需本專案資料層處理。

### 7. PyPortfolio/PyPortfolioOpt：由選股分數轉成受限制的部位配置

- 專案：[PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt)，MIT 授權。[來源](https://github.com/PyPortfolio/PyPortfolioOpt/blob/master/LICENSE)
- README 提供 mean-variance、Black-Litterman、shrinkage 與 Hierarchical Risk Parity，並支援額外目標與限制；範例也包含把連續權重轉為可實際購買的離散股數與剩餘現金。[來源](https://github.com/PyPortfolio/PyPortfolioOpt#pyportfolioopt)

**可套用：**在「今日決策」之後新增「組合建議」而不是再增加單檔分數：總股票曝險依市場狀態上限、單檔 1／5／10% 上限、產業集中上限、持有／觀察分開、現金下限、台股一張／零股交易約束。第一版採可解釋的規則配置；若資料與回測成熟，再評估 HRP 或最小風險法。

**適配與風險：**很符合使用者要用系統投資的目標；平均報酬與共變異數估計容易不穩定，不能把「最大 Sharpe」當未來報酬預測，且必須在歷史回測中驗證交易成本與零股／整張約束。

### 8. polakowo/vectorbt：大量參數實驗與 Walk-forward 穩健性檢查

- 專案：[polakowo/vectorbt](https://github.com/polakowo/vectorbt)；目前社群版為 Apache-2.0 加 Commons Clause（fair-code），README 明言不得把其主要功能作為銷售產品／服務，因此公開商業部署前不適合直接內嵌或衍生使用。[來源](https://github.com/polakowo/vectorbt#license)
- README 主打向量化回測、多資產／參數廣播、交易／回撤分析、Walk-forward robustness testing 與視覺化。[來源](https://github.com/polakowo/vectorbt#features)

**可套用：**借鑑實驗設計而非程式碼：對 vNext 的品質／估值門檻、持有期、再平衡日、交易成本、不同市場狀態做網格測試，保留完整設定與結果；只有在多組合理設定、不同期間都可接受時才考慮保留規則。

**適配與風險：**適合研究環境；目前授權是重要限制。網格搜尋本身也會增加資料探勘偏誤，必須鎖定最後的樣本外測試期。

### 9. fivetran/great_expectations：把「資料不足」升級為可測試的資料契約

- 專案：[fivetran/great_expectations](https://github.com/fivetran/great_expectations)，Apache-2.0 授權。[來源](https://github.com/fivetran/great_expectations/blob/develop/LICENSE)
- README 將 Expectations 定義為可表達、可擴充的資料單元測試，並可自動產生驗證結果文件。[來源](https://github.com/fivetran/great_expectations#about-gx-core)

**可套用：**替每個推薦必要資料集定義本專案自己的契約，例如：日價量最新日不可落後最近交易日 N 日、OHLC 不可為負、現金流連續 12 期、正式 vNext 必須具 5 年財報／600 個交易日、法人資料的市場覆蓋率門檻。失敗就標示「不可作正式推薦」並顯示具體缺哪一項，而非以空值硬算。

**適配與風險：**概念適配度高；完整框架對目前 FastAPI + SQLite 專案可能過重，建議先以 pytest + SQL 檢查與資料品質頁實作，不急於引入大型相依套件。

## 建議的開發順序

1. **資料可信度基線（P0）**：同步佇列＋來源節流／冷卻、品質快照、資料契約與失敗重試頁。這是正式 vNext 回測與「今日決策」可信度的前提。
2. **可稽核 vNext 回測（P0）**：為每次歷史訊號保存可重算快照與 report run；先延長資料，再做未參與調參的樣本外期。
3. **投資組合層（P1）**：把目前單檔「建議部位」整合成總曝險、產業、現金、交易單位都受限的配置提案。
4. **提醒與決策履歷（P1）**：只在評級、部位上限、資料品質或市場狀態改變時提醒，保留改變前後理由與資料時間戳。
5. **研究 UI（P2）**：把 K 線、法人、融資券、股利／除息與資料來源覆蓋率放在同一個可追溯視圖。

## 採用原則

- 優先借鑑架構與驗證方法；除非再做授權審核，不直接複製第三方程式碼或資料。
- 模型輸出必須附資料截至日、來源、覆蓋率與失效條件；資料不足時寧可不推薦。
- 回測必須扣交易成本、以當時可得資料計算、保留所有設定；即使結果良好，也只代表歷史模擬，不代表可獲利。
