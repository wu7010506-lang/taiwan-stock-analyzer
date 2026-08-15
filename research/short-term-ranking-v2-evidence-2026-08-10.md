# 短線排行榜 v2 研究依據

研究日期：2026-08-10  
範圍：TWSE／TPEx、收盤後產生訊號、次一交易日才可能進場、預計持有 3–10 個交易日。

## 實作結論

1. 不再增加彼此高度重疊的震盪指標。MA、RSI、MACD 與短期漲幅都來自價格，排行榜只以趨勢、相對動能、量價、籌碼與可執行性分組評估，避免重複灌分。
2. 將 1–5 日價量衝擊與 20–60 日趨勢分開。爆量急漲不固定加分，因為短期可能先反轉。
3. 個股動能同時與大盤、同產業比較；前十名同產業最多三檔，降低把同一筆產業交易重複押注的風險。
4. ATR 用於停損、最高追價與部位縮放，不作獲利加分。MFI、NATR、RSI 過熱是軟性風險，不單獨否決交易。
5. 交易價值以成本後 RR 評估。假設每邊手續費 0.1425%、賣出證交稅 0.3%、每邊滑價 0.1%；次日實際成交價仍須重算。
6. 事件風險與交易治理分開。除權息或已確認重大負面事件可阻擋執行；處置、注意、暫停交易資料尚未接入時，明確標示限制，不能假裝已檢查。
7. 所有估值、營收、財報、法人資料都切齊到個股訊號日；不同交易日的股票不放在同一排行榜比較。

## 主要證據

- 短期贏家／輸家可能反轉，因此不能把 5 日漲幅直接當成未來報酬：[Lehmann (1990)](https://academic.oup.com/qje/article-abstract/105/1/1/1928416)、[Gutierrez & Kelley (2008)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2008.01320.x)。
- 高成交量同時可能代表資訊擴散或短期反轉，必須與價格方向合併判斷：[Conrad, Hameed & Niden (1994)](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1994.tb02455.x)、[Chordia & Swaminathan (2000)](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00231)。
- 產業動能可解釋相當部分個股動能，因此需做產業調整與集中限制：[Moskowitz & Grinblatt (1999)](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00146)。
- 交易成本可能消除帳面動能利潤：[Lesmond, Schill & Zhou (2004)](https://www.bauer.uh.edu/rsusmel/phd/Lesmond_et%20al%20_2004_JFE.pdf)。
- 台股普通股一般漲跌幅 10%，3–10 日交易一般賣出證交稅為 0.3%：[TWSE 交易制度](https://www.twse.com.tw/zh/products/system/trading.html)、[TWSE 投資指南](https://www.twse.com.tw/zh/about/company/guide.html)。
- 大量試驗會提高假發現與回測過度擬合機率；規則應鎖版後做 walk-forward 與最終樣本外驗證：[Harvey, Liu & Zhu (2016)](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824)、[Bailey et al.](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253)。

## 尚未完成的資料能力

- 處置／分盤、注意股、暫停交易的每日 point-in-time 名單。
- 正式 15 分與 60 分 K。
- 個別券商實際折扣、買賣價差與委託市場衝擊。
- 鎖定 v2 規則後的完整 walk-forward、最終樣本外期與紙上投資組合樣本。

因此 v2 可以提供透明的分析與紙上操作條件，但在上述驗證完成前，不宣稱已具有正期望值，也不開啟自動或正式交易權限。
