# 台股選股器

首頁展開「台股選股器」，第一次先按「建立選股資料集」。系統會一次同步全市場
最新月營收、估值與季報，之後可依市場、產業、營收成長、毛利率、ROE、負債比、
PE、殖利率、RSI 與季線條件篩選。

```text
POST /screener/sync
GET /screener?min_revenue_yoy=10&min_roe=12&max_pe=25
GET /screener/export?min_revenue_yoy=10&min_roe=12&max_pe=25
```

CSV 使用 UTF-8 BOM，可直接以繁體中文 Excel 開啟。技術條件只適用於已補抓足夠
歷史行情的股票；缺少指標的股票不會被當成數值零。
