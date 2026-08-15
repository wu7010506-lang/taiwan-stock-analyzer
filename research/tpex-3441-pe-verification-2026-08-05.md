# 3441 聯一光電本益比：TPEx 官方資料核對

查核日：2026-08-05（台北）  
標的：3441 聯一光電（TPEx 上櫃）

## 結論

截至查核日，TPEx 官方 OpenAPI 最新可得資料的交易日為 **2026-08-04**（民國 `1150804`）。股票代號 `3441` 的官方本益比為 **78.60 倍**。

因此，網站若顯示 67.72，或畫面曾顯示 81，皆不應被當成截至 2026-08-04 的 TPEx 最新官方本益比；應先保留各自的資料日期與來源，再判斷是資料延遲、資料日不同，或計算口徑不同。

## 第一手來源與欄位

- TPEx 官方資料端點：[上櫃股票個股本益比、殖利率、股價淨值比](https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis)
- TPEx 官方 OpenAPI 規格：[swagger.json](https://www.tpex.org.tw/openapi/swagger.json)
- 端點名稱：`/tpex_mainboard_peratio_analysis`
- 官方欄位定義：
  - `Date`：資料日期
  - `SecuritiesCompanyCode`：股票代號
  - `CompanyName`：名稱
  - `PriceEarningRatio`：本益比

本次端點回傳、經 `SecuritiesCompanyCode = "3441"` 篩選後的原始欄位如下：

```json
{
  "Date": "1150804",
  "SecuritiesCompanyCode": "3441",
  "PriceEarningRatio": "78.60",
  "DividendPerShare": "0.85000000",
  "YieldRatio": "0.95",
  "PriceBookRatio": "4.30"
}
```

`1150804` 為民國年格式，換算為西元 **2026-08-04**。

## 系統使用建議

1. 將 TPEx `PriceEarningRatio` 視為上櫃股票的官方每日估值資料，連同 `Date` 一起儲存與呈現。
2. 不可只顯示本益比數字；需同時顯示「來源：TPEx」與「資料日：2026-08-04」。
3. 當本機資料和官方最新資料不一致時，應在資料品質頁標示為「估值資料過期或待核對」，不可靜默用舊值做基本面篩選。

