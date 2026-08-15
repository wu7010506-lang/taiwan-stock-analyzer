const number = (value, suffix = "") => value == null ? "資料不足" : `${Number(value).toLocaleString("zh-TW", {maximumFractionDigits: 2})}${suffix}`;
const card = (title, lines) => `<article class="table-card dashboard-panel"><div class="section-heading"><h2>${title}</h2></div><ul class="dashboard-risk-list">${lines.map(line => `<li>${line}</li>`).join("")}</ul></article>`;

async function loadShortAnalysis() {
  const status = document.querySelector("#analysisStatus");
  const grid = document.querySelector("#analysisGrid");
  try {
    const response = await fetch("/stocks/2454/short-analysis");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "短線分析資料無法讀取");
    status.innerHTML = `<strong>${data.symbol} ${data.name || ""}</strong>｜資料截至 ${data.as_of}｜${data.input_rows} 個交易日｜僅呈現證據，不提供買賣指令。`;
    const trend = data.trend || {}, position = data.long_term_position || {}, risk = data.risk || {};
    const rs = data.relative_strength || {}, donchian = data.donchian || {};
    const guidance = data.research_guidance || {};
    grid.innerHTML = [
      card(`短線研究建議：${guidance.label || "資料不足"}`, [...(guidance.positives || []).map(item => `有利證據：${item}`), ...(guidance.blockers || []).map(item => `尚未確認：${item}`), ...(guidance.review_conditions || []).map(item => `重新檢查條件：${item}`), guidance.risk_notice || ""]),
      card("趨勢與動能", [`收盤 ${number(trend.close)}`, `EMA12／20／26：${number(trend.ema_12)}／${number(trend.ema_20)}／${number(trend.ema_26)}`, `SMA20／60：${number(trend.sma_20)}／${number(trend.sma_60)}`, `MACD／訊號：${number(trend.macd)}／${number(trend.macd_signal)}`, `ADX／+DI／-DI：${number(trend.adx_14)}／${number(trend.plus_di_14)}／${number(trend.minus_di_14)}`]),
      card("產業相對強弱", rs.status === "available" ? [`近 ${rs.sessions} 日個股 ${number(rs.stock_return_percent, "%")}`, `同業等權代理 ${number(rs.industry_return_percent, "%")}`, `相對超額 ${number(rs.excess_return_percent, "%")}`, `可比同業 ${rs.peer_count} 檔`] : ["資料不足：無法建立可靠同業比較"]),
      card("52 週價格位置", [`52 週高／低 ${number(position.high_52w)}／${number(position.low_52w)}`, `距 52 週高點 ${number(position.distance_to_52w_high_percent, "%")}`, `距 52 週低點 ${number(position.distance_to_52w_low_percent, "%")}`]),
      card("風險與波動", [`ATR14 ${number(risk.atr_14)}；NATR ${number(risk.natr_14_percent, "%")}`, `2 ATR 風險參考價 ${number(risk.atr_2x_invalidation_price)}`, `3 ATR 風險參考價 ${number(risk.atr_3x_invalidation_price)}`, `60 日年化歷史波動率 ${number(risk.historical_volatility_annualized_percent, "%")}`, `相對台指 Beta ${number(risk.beta_to_taiex_60d)}`]),
      card("Donchian 區間", [`20 日高／低 ${number(donchian[20]?.high)}／${number(donchian[20]?.low)}；位置 ${number(donchian[20]?.position_percent, "%")}`, `55 日高／低 ${number(donchian[55]?.high)}／${number(donchian[55]?.low)}；位置 ${number(donchian[55]?.position_percent, "%")}`]),
    ].join("");
  } catch (error) { status.textContent = error.message; }
}
loadShortAnalysis();
