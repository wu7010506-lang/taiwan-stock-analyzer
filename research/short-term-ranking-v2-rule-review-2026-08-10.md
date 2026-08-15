# 短線排行榜 v2 規則審查

日期：2026-08-10  
範圍：`short-term-3-10d-v2` 現行程式規則；不執行回測、不修改程式。  
研究方法：只採用交易所官方制度／資料說明、TA-Lib 官方文件及原始學術論文。文獻證據多來自美國或跨市場，不能直接視為台股 3–10 日策略的獲利證明。

## 結論先行

v2 的設計方向是合理的研究框架，不是已證實的獲利策略。它比「看到指標金叉就買」好很多：基本面先篩、收盤突破與成交量作核心確認、ATR 管風險、成本後 RR、次日開盤重查、產業集中限制，以及分析資格與交易權限分離，都是正確的系統化方向。

但目前有四項重大問題：

1. **RR 可能成為循環論證。** 沒有上方結構壓力時，程式以「最低 RR 反推價格」直接當計畫目標，再用同一目標計算成本後 RR。這會讓 RR 幾乎依定義通過，卻沒有證據說明股價到得了該目標。要求的報酬不是預期報酬。
2. **基本面缺值可能被放行。** SQL 使用 `COALESCE(net_income, 0)>=0` 及 `COALESCE(free_cash_flow, 0)>=0`；缺資料會變成 0 並通過，與「基本面是門檻」的原則矛盾。
3. **價格訊號嚴重重複。** MA 排列、20 日相對強弱、5／10 日產業相對強弱、20 日突破、量價、MACD 柱狀體都由相同價格序列衍生，最高可占絕大部分分數。高分代表「同一趨勢被量了很多次」，不等於多項獨立證據。
4. **A／B 分級與可交易含義不夠一致。** B 級只要核心突破條件通過即可，即使成本後 RR 不足或有軟風險也仍列入 `analysis_pass_candidates`。此外，前十名不足時會用第二輪補名單，可能突破「同產業最多三檔」的宣告限制。

因此，**現在的排行榜適合回答「哪些股票值得優先人工檢查」；還不適合回答「今天應買哪一檔」**。修正上述邏輯後，仍需鎖定版本做樣本外或紙上驗證，才能評估正期望值。

## 一、逐項審查

### 1. 基本面安全門檻

現行：負債／資產不高於 70%、最新淨利與 FCF 非負、本益比 0–60、最新月營收 YoY 不低於 0%、財報至少四期、20 日均成交金額至少 500 萬元。

判斷：**基本面作安全門而不直接加技術分是好設計；具體門檻則未被 3–10 日報酬證實，且存在定義與產業偏誤。**

- 獲利能力與低財務困境風險具有廣泛資產定價證據；高困境風險股票反而呈現低平均報酬與高波動。[Campbell、Hilscher、Szilagyi（2008）](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2008.01416.x)、[Novy-Marx（2010/2013）](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1598056)、[Fama–French（2016）](https://academic.oup.com/rfs/article-abstract/29/1/69/1843682)支持避開明顯虧損與困境企業的方向。
- 但文獻支持的是多維度獲利能力、投資與困境風險，不支持「負債比 70%、PE 60 倍、單月營收零成長」能預測未來 3–10 日報酬。
- `total_liabilities / total_assets` 是負債占資產，不是有息負債率。銀行、保險等金融業的負債是營運結構，統一 70% 會造成產業錯殺。
- 單季 FCF 會被資本支出時點、營運資金與季節性扭曲；單月營收 YoY 也可能被工作天、農曆年、匯率及去年基期扭曲。現行做法會排除暫時性負 FCF 的好公司，也可能放過四季趨勢惡化但最新一季略正的公司。
- PE 0–60 是使用者可理解的風險閘門，但不是跨產業可比較的短線訊號。負 PE 被全部排除合理地避開虧損公司；60 倍上限仍是治理選擇，不是研究結論。
- **程式錯誤風險：** `COALESCE(...,0)>=0` 讓淨利或 FCF 缺值等同 0，缺資料反而通過。

可直接修改：

1. 缺失淨利或 FCF 必須明確判為資料不足，不得 `COALESCE` 為 0。
2. 以 TTM／最近四季合計淨利與 FCF 取代單一最新期；另列最近四季負值期數與惡化趨勢。
3. 金融業使用獨立門檻，或先排除金融業，避免用一般產業的負債與 FCF 定義。
4. 單月營收改用近三月累計 YoY 或三月 YoY 中位數；單月負成長作風險標記，不宜永久硬擋。
5. PE 60 保留為治理門檻時，畫面應標示「政策門檻，尚未驗證」，並另顯示產業 PE 百分位。
6. 流動性門檻需同時檢查最低成交價格、20 日成交天數、零成交天數、金額波動與預計部位／ADV，而非只看平均值。

### 2. MA5／10／20／60 趨勢

判斷：**可作狀態分類，但不應給 25 分後又與其他動能指標重複加分。**

[Brock、Lakonishok、LeBaron（1992）](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x)對長期美國指數的移動平均及交易區間突破找到統計支持；但後續研究提醒，技術規則必須處理資料探勘與樣本外衰退。[Sullivan、Timmermann、White 的技術規則研究](https://academic.oup.com/jfec/article/20/4/716/6043099)所涉及的方法論及 [White（2000）Reality Check](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152)正說明：從許多週期與組合中挑出最好者，很可能只是重複試驗的產物。

MA 排列只是價格趨勢的平滑表示，與 5／10／20 日報酬、突破及 MACD 高度共線。`MA5≥MA10≥MA20≥MA60` 可作「趨勢背景」，不應被視為四項證據。

可直接修改：把 MA 排列濃縮為單一「中期趨勢因子」，最多占技術分 20%–25%；避免再讓 MACD、20 日報酬與突破完整重複加分。

### 3. 1／5／10／20 日動能、相對大盤與產業強度

判斷：**產業及市場調整方向正確；3–10 日週期同時存在延續與反轉，不能把所有近期漲幅都當利多。**

- 經典價格動能證據主要是 3–12 個月形成及持有期，不是 3–10 日。[Jegadeesh、Titman（1993）](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x)。
- 產業動能具有獨立資訊，[Moskowitz、Grinblatt（1999）](https://onlinelibrary.wiley.com/doi/pdf/10.1111/0022-1082.00146)發現產業成分可解釋大量個股動能。因此用產業相對強度比只看個股漲幅合理。
- 然而一週極端贏家在下一週可先反轉，較不極端者則可能延續；[Gutierrez、Kelley（2008）](https://rogutierrez.net/files/Weekly.pdf)顯示第一週反轉集中在極端組別，之後才出現較長的動能。這與 v2 的 3–10 日持有期直接相關。

現行產業基準還有兩個問題：只用「通過基本面門檻的候選」計算產業中位數，產業樣本會因基本面篩選而改變；且個股本身被包含在產業中位數，小產業會自我影響。

可直接修改：

1. 把 20／60 日趨勢與 1／5 日價格衝擊拆開：中期趨勢決定方向，短期極端漲幅只作追價／反轉風險。
2. 產業報酬應由完整可交易產業股票池計算，不是只用基本面候選；使用 leave-one-out 中位數，並設定至少 5–10 檔成分股，否則標示不足。
3. 相對大盤及相對產業回報保留一個殘差動能分數；不要同時計滿個股 5／10／20 日報酬。
4. 單日漲幅、跳空或 5 日漲幅達歷史／橫截面極端百分位時，降低追價資格，等回測支撐或第二次確認。

### 4. 5／20 日量比與突破量能

判斷：**成交量確認有經濟直覺，但「量大＝好」不成立；目前硬門檻 1.2／1.3／1.5 沒有台股 v2 證據。**

[Lee、Swaminathan（2000）](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00280)顯示過去成交量能區分動能的幅度與持續性，但高量贏家的反轉也更快。[Campbell、Grossman、Wang（1993）](https://www.nber.org/papers/w4193)指出量與報酬自相關的關係取決於交易壓力與流動性供給。因此放量上漲可增加突破可信度，極端放量也可能代表擁擠或最後衝刺。

現行規則用 20 日量比作硬門檻，又在排行對 `volume_ratio_20>=1.2` 加分，造成同一條件重複影響資格與名次；5 日量比雖輸出但未形成清楚的獨立用途。

可直接修改：用「價格方向 × 量比 × 距離突破 × 短期極端度」分類：溫和放量突破加分、爆量長上影或大跌扣分、縮量突破不成立。量比門檻需以股票自身及產業歷史百分位標準化；固定 1.2／1.3／1.5 保留時標示為未驗證參數。

### 5. 20 日收盤突破

判斷：**收盤確認比盤中碰到可靠；20 日窗口與 3–10 日持有期仍是待驗證假設。**

交易區間突破在 [Brock 等（1992）](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x)有研究支持，接近歷史高點也與較長期動能有關；但 52 週高點研究不能直接證明 20 日高點對台股 3–10 日有效。現行「收盤大於先前 20 日高點」是清楚、不可主觀改動的觸發條件，這點很好。

可直接修改：突破只作觸發器，不另給大量排行分；將「突破幅度／ATR、收盤在當日區間位置、上影線、隔日開盤缺口」納入成交品質，而非降低突破標準。

### 6. RSI、MFI、NATR 軟風險

判斷：**改為軟風險是正確的；70／80／7% 都是待驗證門檻，且 MFI、RSI 與現有價格量能訊號重疊。**

TA-Lib 官方只定義如何計算，不證明獲利能力；其文件並註明 RSI、MFI、ATR、NATR 有 unstable period。[TA-Lib 動能指標](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html)、[TA-Lib 波動指標](https://ta-lib.github.io/ta-lib-python/func_groups/volatility_indicators.html)。因此「TA-Lib 算得正確」不等於「80 是有效超買線」。

可直接修改：保留軟風險，不一票否決；改用股票自身 252 日及同產業橫截面百分位。NATR 用於部位與最大損失，不宜同時當負向選股分數；MFI 若與量價狀態高度重複，可只顯示證據，不計分。

### 7. MACD 柱狀體變化

判斷：**作解釋資訊可以，獨立加分價值低。**

MACD(12,26,9)是 EMA 的差再減訊號線；TA-Lib 官方公式介面確認其輸入仍只有收盤價。[TA-Lib MACD](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html)。它和 MA 排列、近期報酬、突破不是獨立資料來源。

可直接修改：MACD 柱狀體變化只作「趨勢是否加速／減速」的說明或同分決勝，不再固定加 5 分。若保留加分，必須降低 MA／報酬因子權重並做相關性監控。

### 8. 外資／投信五日買賣超

判斷：**資料是真實可驗證的，但正買超不能直接解讀為未來上漲。**

TWSE 官方資料逐日提供外資、投信買進、賣出及差額，資料可追溯至 2004 年；TPEx 官方頁面可查至 2012 年。[TWSE 每日三大法人資料說明](https://eshop.twse.com.tw/en/product/detail/6edec1b6e62345cb9f1244acbbcefae0)、[TPEx 法人買賣明細](https://www.tpex.org.tw/en-us/mainboard/trading/major-institutional/3itrade/day.html)。

台灣研究顯示法人常具有動能／回饋交易行為，但不代表跟單有超額報酬；外資的錨定甚至可能降低動能獲利。[Liao、Chou、Chiu（2013）](https://www.sciencedirect.com/science/article/pii/S1062940813000703)。因此五日買超既可能是資訊，也可能是追價、價格影響或已反映在股價中。

現行把外資與投信標準化後相加，只要合計為正就加 8 分，會掩蓋兩者方向相反，也未剔除「漲了所以法人買」的同時性。

可直接修改：外資與投信分開顯示／計分；以流通股數或成交量標準化並做橫截面百分位；使用截至訊號日收盤已公布的資料；以「買超創新＋價格尚未極端」為輔助，不能當核心入場依據。缺資料不應當零，也不該自動扣分。

### 9. ATR 停損、最高追價與 NATR 部位縮放

判斷：**風險框架方向佳；1.5 ATR、0.25 ATR、5%／7%縮放都是治理參數，不是已證實最優值。**

高波動降低曝險有較強的一般性研究支持；[Moreira、Muir（2017）](https://www.nber.org/papers/w22208)發現高波動時降低風險可改善多種因子的 Sharpe ratio。但該研究是組合波動管理，不直接驗證單檔 NATR 5%／7%、1.5 ATR 停損或 0.25 ATR 追價。

現行停損取「突破 K 低點」與「進場−1.5 ATR」較高者，能限制名目風險；但若結構低點距離超過 1.5 ATR，直接把停損移近會改變原本的價格結構邏輯，可能只增加雜訊停損。跳空跌破時，實際損失仍可大於 1.5 ATR。

可直接修改：

1. 結構停損超過風險預算時，優先「降低部位或放棄交易」，不要自動移動結構失效點。
2. 最高進場價 0.25 ATR 保留為暫定參數；次日以實際開盤、台股跳動單位及成本重算全部風險與 RR。
3. 部位以「帳戶可承受損失／每股含成本及跳空緩衝的風險」計算，NATR 只作額外上限。
4. 加入組合層級單日最大新增風險、總開放風險與同產業風險，而非只限制單檔百分比。

### 10. 動態量比與動態 RR

判斷：**依市場狀態調整是合理假說，但現有映射沒有實證支持；RR 目前還有嚴重的自我通過問題。**

現行映射：趨勢／盤整／防守市場的量比分別 1.2／1.3／1.5，最低 RR 分別 1.5／2／3。這是清楚可執行的預先登錄規則，優於每次任意改動；但沒有論文能直接證明此離散映射適合台股。

更重要的是，當沒有下一個 55 日結構壓力時，程式將「達到最低成本後 RR 所需的價格」當 `planned_target`。之後用該目標重算 RR，結果自然接近最低要求。**這不是對交易價值的驗證，只是代數恆等。**

可直接修改：

1. 分開 `required_target`（為達 RR 必須到達）與 `expected/structural_target`（由市場結構或經驗分布估計）。
2. 沒有獨立可推導的目標時，RR 狀態應為「無法驗證」，不得因此升為 A／B。
3. 結構目標低於 required target 時直接顯示不合格；結構目標高於 required target 才能通過。
4. 市場狀態應主要調整部位、最大總風險及交易頻率；提高名目 RR 目標並不會自動提高預期報酬。
5. 三組量比與 RR 門檻鎖版，未來只能用事先定義的樣本外比較更換，並記錄所有試過的版本。[White（2000）](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152)、[Bailey 等（2014）](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)說明了重複試參數造成回測過度擬合的風險。

### 11. 成本後 RR、次日開盤與流動性

判斷：**納入成本與次日重查是 v2 最強的部分；固定滑價仍不足以表示真實可成交性。**

TWSE 官方說明：一般股票每日漲跌幅原則為 10%，開盤採集合競價；一般股票賣出證交稅為 0.3%，券商佣金由券商自行訂價，0.1425%是標準參考。[TWSE 交易制度](https://www.twse.com.tw/en/products/system/trading.html)。因此訊號收盤不等於可成交價，次日開盤若漲停、集合競價量不足或處置交易，可能買不到；固定 10 bps 滑價也無法反映價格衝擊。

動能利潤對成本與容量敏感；[Korajczyk、Sadka 相關研究摘要](https://www.nber.org/system/files/working_papers/w18169/revisions/w18169.rev1.pdf)及 [NBER 市場流動性研究](https://www.nber.org/papers/w33037)均強調成交量、交易規模和淨成本績效的重要性。

可直接修改：

1. 實際候選須以次日開盤價重算停損距離、成本、結構目標及 RR，不只是檢查是否低於最高進場價。
2. 價格、停損、目標都按 TWSE／TPEx 跳動單位取整，且方向採保守取整。
3. 成本模型除佣金、稅、固定滑價外，加入半價差及部位／ADV 的衝擊函數；公開使用者實際券商折扣與最低手續費。
4. 1% ADV 是合理的保守起點，但 500 萬元 ADV 的 1% 只有 5 萬元；需顯示是否足以買一張，並支援零股時說明交易時段差異。
5. 加入漲停無成交、延後開盤、處置分盤、暫停交易、變更交易及企業行動硬閘門。TWSE 官方另有[處置證券公告](https://www.twse.com.tw/en/announcement/punish.html)與注意／處置資料產品。

### 12. 產業集中與前十名

判斷：**每產業最多三檔方向正確，但目前實作不是絕對限制。**

產業動能意味著同產業股票可能同時高分；這也代表它們不是十筆獨立風險。限制產業集中可防止排行榜其實只押一個題材。

現行第一輪遵守每產業三檔；若不足十檔，第二輪直接用尚未選取的股票補滿，可能讓某產業超過三檔。因此 API 宣告的 maximum 與實際名單可能不一致。

可直接修改：硬上限就不補滿，允許「今天只有 7 檔」；若業務上一定要十檔，超額項目必須標記為「補充研究，不符合產業上限」，不能仍稱正式前十名。組合層級應限制產業總資金與總風險，而不只股票數。

### 13. A／B／C／D 與策略治理

判斷：**分析權限和交易權限分離非常正確；分級語意需要修正。**

現行：A＝核心條件、RR、軟風險均通過；B＝核心條件通過，但可能 RR 不足或有軟風險；C＝趨勢成立、等突破；D＝事件阻擋或核心不符。`analysis_pass_candidates` 又把 A 與 B 都算通過。

問題是 B 可能成本後 RR 不合格，卻用「分析通過」名稱輸出。使用者很容易把排名第一的 B 理解為接近可買，而不是「突破了但交易價值仍不足」。排行分數也沒有被校準成成功機率、預期報酬或信賴度。

可直接修改：

- A：核心觸發、可驗證的成本後 RR、事件與可成交性均通過；仍僅紙上執行，直到治理開放。
- B：核心觸發但存在軟風險；RR 必須仍通過。若 RR 不足，不能是 B。
- C：未觸發但趨勢／基本面符合，列明距離與缺一條件。
- D：基本面、事件、流動性或核心結構不符。
- 額外獨立欄位：`analysis_quality`、`execution_readiness`、`validation_status`、`data_completeness`，不要用一個字母混合四種概念。
- 排行分數明確標為「研究優先分」，不可轉譯為上漲機率。

## 二、訊號重複與目前評分的結構性問題

現行研究優先分的大致來源為：MA 完整多頭 25、相對大盤最多 15、相對產業最多 15、核心突破完成 20、放量上漲 12、MACD 柱狀體增加 5、法人流入 8，合計可達 100 分以上再截斷。

其中 MA、個股相對報酬、產業相對報酬、突破、放量當日報酬、MACD 至少六項直接或間接由同一段價格走勢產生。這會造成：

- 趨勢股在多個欄位重複得分，分數沒有機率意義。
- 1–5 日過熱與 20 日趨勢被混在一起，容易在短期反轉風險最高時排第一。
- 某項缺資料時，分數尺度改變；不同股票的 70 分未必可比較。
- 加入新指標通常只是增加同源噪音，不是增加獨立證據。

建議改為四個互斥層：

1. **資格層（不計分）：** point-in-time 基本面、資料完整、流動性與事件。
2. **方向層（最多 35%）：** 單一殘差趨勢因子，結合 20／60 日走勢、相對市場與產業，不重複計 MA／MACD。
3. **觸發層（最多 30%）：** 20 日收盤突破、收盤位置與適度量能；未觸發就只列 C。
4. **交易品質層（最多 35%）：** 獨立結構目標的成本後 RR、跳空／限價可成交性、波動與流動性。法人只作附加證據或同分排序。

短期極端報酬、MFI、NATR、長上影與爆量應作共同的「追價風險」，不要各自重複扣分。

## 三、台股制度特有風險

1. **10% 漲跌幅與開盤集合競價：** 次日開盤不是保證成交；漲停鎖死時，歷史 OHLC 顯示開盤價也不代表策略買得到。[TWSE 交易制度](https://www.twse.com.tw/en/products/system/trading.html)。
2. **價格跳動單位：** 不同價格區間的 tick 不同，ATR 推導的任意小數價格不是合法委託價。
3. **處置、注意、變更交易與暫停：** 可能延長撮合、要求預收款券或不能採一般訂單；未串完整清單前，可成交性會被高估。[TWSE 處置證券](https://www.twse.com.tw/en/announcement/punish.html)。
4. **除權息、減資與新上市前五日：** 未正確還原會製造假突破、假缺口與錯誤 ATR。新上市普通股前五日另有無漲跌幅例外。[TWSE 官方投資指南](https://www.twse.com.tw/en/about/company/guide.html)。
5. **TWSE 與 TPEx 微結構差異：** 同一 500 萬元流動性門檻不一定代表相同價差與衝擊；績效應分市場報告。

## 四、可直接採用的修正優先序

### P0：先修邏輯正確性

1. 禁止缺失淨利／FCF以 0 通過。
2. `required_target` 不得當成 `planned/expected_target`；沒有獨立目標就把 RR 標為無法驗證。
3. B 級也必須通過可驗證的成本後 RR；否則降 C／D 並列明原因。
4. 同產業三檔若是硬限制，就不可為了湊十檔而突破。

### P1：消除重複與改善執行真實性

1. MA、20 日報酬、突破與 MACD 合併成少數正交／不重複因子。
2. 分離中期趨勢與 1／5 日極端衝擊，對爆量急漲、跳空與長上影設追價風險。
3. 產業基準改用完整可交易股票池、leave-one-out 與最低成分數。
4. 次日依實際開盤重新計算全部風險、目標、成本後 RR；納入 tick、價差、價格衝擊及漲停未成交。
5. 串接 TWSE／TPEx 注意、處置、變更交易、暫停及企業行動資料。

### P2：改善門檻與治理

1. 最新單季／單月門檻改成 TTM 與三月聚合；金融業另設模型。
2. RSI／MFI／NATR 與量比改用自身歷史及產業百分位，不把教科書門檻當自然常數。
3. 外資、投信分開，剔除與近期報酬的重複部分。
4. 所有 20／60 日、1.5 ATR、0.25 ATR、1.2／1.3／1.5、RR 1.5／2／3 都登記為「待驗證參數」，鎖版後不因結果任意調整。

## 五、最終評等

| 面向 | 評等 | 原因 |
|---|---|---|
| 系統化與可解釋性 | 良好 | 規則明確、分析／治理分離、資料日期及限制可揭露 |
| 訊號的經濟直覺 | 中上 | 趨勢、相對強度、量價、波動及成本均有合理研究方向 |
| 參數證據 | 弱 | 多數固定門檻未由台股 3–10 日樣本外資料支持 |
| 訊號獨立性 | 弱 | 多個價格衍生指標重複計分 |
| 風險管理 | 中上 | ATR、次日追價、成本後 RR、部位縮放方向正確；跳空與目標可達性仍不足 |
| 台股可成交性 | 中下 | 尚缺完整處置／暫停／企業行動與真實撮合模型 |
| 可直接下單程度 | 不合格 | RR 自我通過、缺值門檻與分級語意需先修；且尚無樣本外證據 |

整體判斷：**保留 v2，不要推翻；先把它從「很多合理指標的加權表」改成「資格—方向—觸發—交易品質—治理」五層系統。** 最值得保留的是收盤突破、成交量確認、ATR／流動性風控、成本後計算與治理分離；最應刪減的是 MA／近期報酬／MACD／突破的重複加分。參數在沒有樣本外證據前只能稱研究假設，不能稱獲利規則。

## 主要來源

- [TWSE Trading Mechanism Introduction](https://www.twse.com.tw/en/products/system/trading.html)
- [TWSE 2025 Guide to Investing in Taiwan](https://www.twse.com.tw/en/about/company/guide.html)
- [TWSE Announcement of Disposition Securities](https://www.twse.com.tw/en/announcement/punish.html)
- [TWSE Daily Trading Details of Foreign and Institutional Investors](https://eshop.twse.com.tw/en/product/detail/6edec1b6e62345cb9f1244acbbcefae0)
- [TPEx Foreign & Institutional Investors Trading Detail](https://www.tpex.org.tw/en-us/mainboard/trading/major-institutional/3itrade/day.html)
- [TA-Lib function list](https://ta-lib.github.io/function.html)
- [TA-Lib momentum indicators](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html)
- [TA-Lib volatility indicators](https://ta-lib.github.io/ta-lib-python/func_groups/volatility_indicators.html)
- [Brock, Lakonishok & LeBaron (1992)](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x)
- [Jegadeesh & Titman (1993)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x)
- [Moskowitz & Grinblatt (1999)](https://onlinelibrary.wiley.com/doi/pdf/10.1111/0022-1082.00146)
- [Lee & Swaminathan (2000)](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00280)
- [Campbell, Grossman & Wang (1993)](https://www.nber.org/papers/w4193)
- [Gutierrez & Kelley (2008)](https://rogutierrez.net/files/Weekly.pdf)
- [Campbell, Hilscher & Szilagyi (2008)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2008.01416.x)
- [Novy-Marx, The Other Side of Value](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1598056)
- [Fama & French, Dissecting Anomalies with a Five-Factor Model](https://academic.oup.com/rfs/article-abstract/29/1/69/1843682)
- [Moreira & Muir, Volatility Managed Portfolios](https://www.nber.org/papers/w22208)
- [White, A Reality Check for Data Snooping](https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152)
- [Bailey et al., Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)
- [Liao, Chou & Chiu, Taiwan foreign institutional momentum behavior](https://www.sciencedirect.com/science/article/pii/S1062940813000703)
