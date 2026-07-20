# 台股分析程式

第一版 MVP，從臺灣證券交易所（TWSE）與證券櫃檯買賣中心（TPEx）官方
OpenAPI 取得上市、上櫃股票基本資料與最新日行情，儲存至 SQLite，並提供
FastAPI 查詢與技術分析。

## 啟動

```powershell
cd taiwan-stock-analyzer
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

一般使用者請開啟 `http://127.0.0.1:8000/`，即可使用圖形介面搜尋股票、
同步歷史行情並查看圖表與指標。選取搜尋結果後，介面會自動更新近 1 年行情、
月營收、估值與最新財報；同一股票在單次頁面工作階段只會自動同步一次。

開發或除錯時可開啟 `http://127.0.0.1:8000/docs`，依序執行：

1. `POST /sync`：同步上市、上櫃資料。
2. `GET /stocks?q=台積電`：搜尋股票。
3. `GET /stocks/2330/prices`：取得行情。
4. `GET /stocks/2330/analysis`：取得技術分析。

## 補抓歷史行情

先執行一次 `POST /sync` 建立股票清單，再於 Swagger 執行：

```text
POST /history/sync?symbol=2330&start=2023-01-01&end=2026-07-19
```

同步進度與結果可由下列端點查看：

```text
GET /history/status?symbol=2330
GET /stocks/2330/prices?start=2023-01-01&end=2026-07-19&limit=1000
GET /stocks/2330/analysis
```

歷史資料按月向官方端點取得。已存在的日期會以 upsert 更新，因此中斷後可安全
重新執行；每次執行的完成月份、寫入筆數與錯誤會保存在 `sync_runs`。

## 月營收分析

圖形介面選定股票後，可直接設定起訖月份並按「同步月營收」。API 操作方式如下：

```text
POST /revenue/sync?symbol=2330&start=2023-01&end=2026-06
GET /stocks/2330/revenue
GET /stocks/2330/revenue/analysis
```

系統會計算 MoM、YoY、近 3／6／12 月累計年增、連續正成長月數與歷史營收分位。
資料庫金額單位保留為官方的「新台幣仟元」，使用者介面顯示為億元。

## 估值分析

圖形介面可按月同步 PE、PB 與殖利率。系統會在每個月份選擇最後可取得的交易日，
並自動計算歷史分位與相對區間：

```text
POST /valuation/sync?symbol=2330&start=2023-01&end=2026-07
GET /stocks/2330/valuations
GET /stocks/2330/valuations/analysis
```

歷史分位是該股票和自身歷史比較的相對位置，不等同於投資建議，也不應單獨用來
判定高估或低估。

## 季度財務分析

選定股票後按「同步最新財報」，系統會自動辨識一般業、金融業、證券、金控、
保險或異業報表，整合損益表與資產負債表：

```text
POST /financials/sync?symbol=2330
GET /stocks/2330/financials
GET /stocks/2330/financials/analysis
```

一般產業可取得 EPS、毛利率、營業利益率、淨利率、年化 ROE、負債比、流動比率
與每股淨值。特殊產業不適用的欄位會回傳 `null`，不以其他科目硬套計算。

## 注意事項

- 歷史行情目前需逐檔補抓；一次抓取多年資料會依月份產生多次官方請求。
- API 欄位可能變更，Provider 會將格式錯誤隔離為單一市場同步錯誤。
- 本程式提供研究資料，不構成投資建議。公開或商業使用前，請再次確認資料授權。

## 下一階段

- 歷史行情補抓與交易日排程
- 除權息還原價格
- 月營收、三大財報與估值指標
- 選股器、回測與 Streamlit 儀表板
