const $ = (selector) => document.querySelector(selector);
const state = {
  stock: null, prices: [], analysis: null, revenues: [], revenueAnalysis: null,
  valuations: [], valuationAnalysis: null, financials: [], financialAnalysis: null,
  dividends: [], ownership: null, institutions: [], company: null, score: null,
  technical: null, shortTermAnalysis: null, shortTermPosition: null,
  autoSyncedSymbols: new Set(),
};
let toastTimer;

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = "toast", 3200);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) throw new Error(payload?.detail || `請求失敗（${response.status}）`);
  return payload;
}

function setBusy(button, busy, label) {
  if (busy) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.label;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

async function checkHealth() {
  const el = $("#apiStatus");
  try {
    await api("/health");
    el.className = "status-dot online";
    el.innerHTML = "<i></i>服務正常";
  } catch {
    el.className = "status-dot offline";
    el.innerHTML = "<i></i>服務中斷";
  }
}

async function syncMarket() {
  const button = $("#marketSyncButton");
  setBusy(button, true, "更新中…");
  try {
    const result = await api("/sync", { method: "POST" });
    const twse = result.TWSE?.instruments || 0;
    const tpex = result.TPEx?.instruments || 0;
    toast(`更新完成：上市 ${twse} 檔、上櫃 ${tpex} 檔`);
  } catch (error) { toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function searchStocks() {
  const q = $("#stockSearch").value.trim();
  const resultBox = $("#searchResults");
  if (!q) { resultBox.innerHTML = ""; return; }
  resultBox.innerHTML = "<span>搜尋中…</span>";
  try {
    const stocks = await api(`/stocks?q=${encodeURIComponent(q)}&limit=8`);
    if (!stocks.length) {
      resultBox.innerHTML = "<span>查無結果，請確認是否已更新全市場清單。</span>";
      return;
    }
    resultBox.innerHTML = stocks.map((stock, index) => `
      <button class="result-item" data-index="${index}" type="button">
        <strong>${stock.symbol}</strong>${stock.name}<span>${stock.market}</span>
      </button>`).join("");
    resultBox.querySelectorAll("button").forEach(button => {
      button.addEventListener("click", () => selectStock(stocks[Number(button.dataset.index)]));
    });
  } catch (error) {
    resultBox.innerHTML = "";
    toast(error.message, true);
  }
}

async function openStockFromUrl() {
  const symbol = new URLSearchParams(window.location.search).get("symbol");
  if (!symbol) return;
  try {
    const stocks = await api(`/stocks?q=${encodeURIComponent(symbol)}&limit=8`);
    const stock = stocks.find(item => item.symbol === symbol);
    if (stock) await selectStock(stock);
  } catch (error) { toast(error.message, true); }
}

async function selectStock(stock) {
  state.stock = stock;
  $("#stockSymbol").textContent = stock.symbol;
  $("#stockName").textContent = stock.name;
  $("#stockMarket").textContent = stock.market;
  $("#searchResults").innerHTML = "";
  $("#stockSearch").value = `${stock.symbol} ${stock.name}`;
  $("#emptyState").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  await refreshWatchlistButton();
  await loadStock();
  await autoSyncStockData(stock.symbol);
}

async function refreshWatchlistButton() {
  const button = $("#watchlistButton");
  if (!state.stock) return;
  try {
    const result = await api(`/watchlist/${state.stock.symbol}/status`);
    button.dataset.watched = String(result.watched);
    button.textContent = result.watched ? "✓ 已加入我的股票" : "＋ 加入我的股票";
  } catch { button.textContent = "＋ 加入我的股票"; }
}

async function toggleWatchlist() {
  if (!state.stock) return;
  const button = $("#watchlistButton");
  const watched = button.dataset.watched === "true";
  button.disabled = true;
  try {
    await api(`/watchlist/${state.stock.symbol}`, { method: watched ? "DELETE" : "PUT" });
    await refreshWatchlistButton();
    toast(watched ? "已從我的股票移除" : "已加入我的股票");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

function localDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function autoSyncStockData(symbol) {
  if (state.autoSyncedSymbols.has(symbol)) return;
  state.autoSyncedSymbols.add(symbol);

  const messages = ["#syncMessage", "#revenueSyncMessage", "#valuationSyncMessage", "#financialSyncMessage", "#dividendSyncMessage", "#ownershipSyncMessage", "#institutionSyncMessage"];
  const labels = ["行情", "營收", "估值", "財報", "股利與除權息", "股權分散", "法人買賣"];
  let plan;
  try { plan = await api(`/stocks/${encodeURIComponent(symbol)}/sync-plan`); }
  catch (error) { toast(error.message, true); return; }
  if (plan.ready) {
    messages.forEach((selector, index) => $(selector).textContent = `${labels[index]}資料已是最新，不需重複同步`);
    return;
  }
  messages.forEach((selector, index) => $(selector).textContent = plan.missing.includes(["prices", "revenues", "valuations", "financials", "dividends", "ownership", "institutions"][index]) ? "資料缺少或過期，正在補齊…" : `${labels[index]}資料已是最新`);
  toast(`正在補齊 ${plan.missing.map(name => ({prices:"行情",revenues:"營收",valuations:"估值",financials:"財報",dividends:"股利",ownership:"股權",institutions:"法人"})[name]).join("、")}…`);
  let result;
  try { result = await api(`/stocks/${encodeURIComponent(symbol)}/sync-missing`, { method: "POST" }); }
  catch (error) { toast(error.message, true); return; }
  const keys = ["prices", "revenues", "valuations", "financials", "dividends", "ownership", "institutions"];
  keys.forEach((key, index) => {
    const item = result.results[key];
    $(messages[index]).textContent = !item ? `${labels[index]}資料已是最新` : item.status === "failed" ? `自動同步未完成：${item.error}` : `自動同步完成（${labels[index]}）`;
  });
  if (state.stock?.symbol !== symbol) return;
  await loadStock();
  const failed = result.remaining.length;
  toast(failed ? `資料已更新，但仍有 ${failed} 項缺漏` : "缺少的資料已補齊", failed > 0);
}

async function loadStock() {
  const symbol = state.stock.symbol;
  try {
    const [prices, analysis, revenues, revenueAnalysis, valuations, valuationAnalysis, financials, financialAnalysis, dividends, ownership, institutions, company, score, technical, shortTermAnalysis, shortTermPositions] = await Promise.all([
      api(`/stocks/${symbol}/prices?limit=1000`).catch(() => []),
      api(`/stocks/${symbol}/analysis`).catch(() => null),
      api(`/stocks/${symbol}/revenue?limit=60`).catch(() => []),
      api(`/stocks/${symbol}/revenue/analysis`).catch(() => null),
      api(`/stocks/${symbol}/valuations?limit=120`).catch(() => []),
      api(`/stocks/${symbol}/valuations/analysis`).catch(() => null),
      api(`/stocks/${symbol}/financials?limit=20`).catch(() => []),
      api(`/stocks/${symbol}/financials/analysis`).catch(() => null),
      api(`/stocks/${symbol}/dividends?limit=20`).catch(() => []),
      api(`/stocks/${symbol}/ownership`).catch(() => null),
      api(`/stocks/${symbol}/institutions?limit=60`).catch(() => []),
      api(`/stocks/${symbol}/company`).catch(() => null),
      api(`/stocks/${symbol}/score`).catch(() => null),
      api(`/stocks/${symbol}/technical?limit=300`).catch(() => null),
      api(`/stocks/${symbol}/short-analysis`).catch(() => null),
      api("/short-term-positions").catch(() => ({ positions: [] })),
    ]);
    state.prices = prices;
    state.analysis = analysis;
    state.revenues = revenues;
    state.revenueAnalysis = revenueAnalysis;
    state.valuations = valuations;
    state.valuationAnalysis = valuationAnalysis;
    state.financials = financials;
    state.financialAnalysis = financialAnalysis;
    state.dividends = dividends;
    state.ownership = ownership;
    state.institutions = institutions;
    state.company = company;
    state.score = score;
    state.technical = technical;
    state.shortTermAnalysis = shortTermAnalysis;
    state.shortTermPosition = (shortTermPositions.positions || []).find(position => position.symbol === symbol) || null;
    renderQuote();
    renderAnalysis();
    renderTechnicalIndicators();
    renderShortTermAnalysis();
    renderShortPositionControl();
    renderTable();
    scheduleChartDraw();
    renderRevenue();
    drawRevenueChart();
    renderValuation();
    drawValuationChart();
    renderFinancials();
    renderDividends();
    renderOwnership();
    renderInstitutions();
    renderCompanyProfile();
    renderStockScore();
  } catch (error) { toast(error.message, true); }
}

function formatRevenue(thousands) {
  if (thousands === null || thousands === undefined) return "—";
  return `${formatNumber(Number(thousands) / 100000, 2)} 億`;
}

function profileDate(value) {
  const text = String(value || "").replace(/\D/g, "");
  return text.length === 8 ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : value || "—";
}

function renderCompanyProfile() {
  const company = state.company;
  $("#companyIndustry").textContent = company?.industry_name || "產業未分類";
  $("#companyBusinessSummary").textContent = company?.business_summary || "目前沒有可用的公司基本資料。";
  const facts = [
    ["董事長", company?.chairman || "—"],
    ["成立日期", profileDate(company?.established_date)],
    [company?.market === "TPEx" ? "上櫃日期" : "上市日期", profileDate(company?.listed_date)],
  ];
  $("#companyFacts").innerHTML = facts.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")
    + (company?.website ? `<a href="${company.website}" target="_blank" rel="noopener">前往公司官方網站 ↗</a>` : "");
}

function renderStockScore() {
  const data = state.score;
  const score = data?.score;
  const gauge = $("#scoreGauge");
  gauge.style.setProperty("--score", score || 0);
  gauge.innerHTML = `<strong>${score == null ? "—" : formatNumber(score, 1)}</strong><span>${data?.label || "資料不足"}</span>`;
  $("#scoreCoverage").textContent = data ? `資料完整度 ${data.coverage}%` : "尚無評分";
  $("#scoreDimensions").innerHTML = data ? data.dimensions.map(item => `
    <div><span>${item.label}</span><i><b style="width:${item.score || 0}%"></b></i><strong>${item.score == null ? "—" : formatNumber(item.score, 1)}</strong></div>
  `).join("") : "";
  const list = (items, empty) => items?.length ? items.map(item => `<li>${item}</li>`).join("") : `<li>${empty}</li>`;
  $("#scoreStrengths").innerHTML = list(data?.strengths, "目前沒有達到 70 分的面向");
  $("#scoreRisks").innerHTML = list(data?.risks, "目前沒有低於 40 分的面向");
  $("#scoreMetricDetails").innerHTML = data ? data.dimensions.map(dimension => `
    <section><h4>${dimension.label} · ${dimension.score == null ? "—" : formatNumber(dimension.score, 1)} 分</h4>${dimension.metrics.map(metric => `<div><span>${metric.label}</span><strong>${metric.score == null ? "未計分" : formatNumber(metric.score, 1)}</strong><small>${metric.detail}</small></div>`).join("")}</section>
  `).join("") : "尚無資料";
}

function formatGrowth(value) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}

function renderRevenue() {
  const a = state.revenueAnalysis;
  $("#revenueDate").textContent = a ? `最新申報 ${a.as_of}` : "尚未同步";
  const items = [
    ["當月營收", formatRevenue(a?.revenue_thousands)],
    ["月增率 MoM", formatGrowth(a?.mom_percent)],
    ["年增率 YoY", formatGrowth(a?.yoy_percent)],
    ["近 3 月年增", formatGrowth(a?.rolling_3m_yoy_percent)],
    ["近 6 月年增", formatGrowth(a?.rolling_6m_yoy_percent)],
    ["近 12 月年增", formatGrowth(a?.rolling_12m_yoy_percent)],
    ["連續正成長", a ? `${a.consecutive_positive_yoy_months} 個月` : "—"],
    ["歷史營收分位", a ? `${formatNumber(a.historical_percentile, 1)}%` : "—"],
  ];
  $("#revenueMetricGrid").innerHTML = items.map(([label, value]) => `
    <div class="revenue-stat"><span>${label}</span><strong>${value}</strong></div>
  `).join("");
}

function drawRevenueChart() {
  const rows = state.revenues.slice(-36);
  const canvas = $("#revenueChart"), empty = $("#revenueChartEmpty");
  if (!rows.length) { empty.hidden = false; canvas.hidden = true; return; }
  empty.hidden = true; canvas.hidden = false;
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio; canvas.height = rect.height * ratio;
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const width = rect.width, height = rect.height, pad = { t: 14, r: 58, b: 30, l: 8 };
  const values = rows.map(row => Number(row.revenue) / 100000);
  const max = Math.max(...values) * 1.12 || 1;
  const chartWidth = width - pad.l - pad.r, chartHeight = height - pad.t - pad.b;
  const step = chartWidth / rows.length, barWidth = Math.max(2, step * .62);
  ctx.font = "11px Segoe UI"; ctx.fillStyle = "#68736d"; ctx.strokeStyle = "#d9ddd7";
  for (let i = 0; i < 5; i++) {
    const value = max * i / 4, y = pad.t + chartHeight - value / max * chartHeight;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(width - pad.r, y); ctx.stroke();
    ctx.fillText(formatNumber(value, 0), width - pad.r + 8, y + 4);
  }
  rows.forEach((row, index) => {
    const value = values[index], x = pad.l + index * step + (step - barWidth) / 2;
    const barHeight = value / max * chartHeight;
    ctx.fillStyle = row.yoy_percent >= 0 ? "rgba(13,103,75,.78)" : "rgba(179,58,58,.7)";
    ctx.fillRect(x, pad.t + chartHeight - barHeight, barWidth, barHeight);
  });
  ctx.fillStyle = "#68736d";
  ctx.fillText(rows[0].revenue_month, pad.l, height - 7);
  const end = rows.at(-1).revenue_month;
  ctx.fillText(end, width - pad.r - ctx.measureText(end).width, height - 7);
}

function renderValuation() {
  const a = state.valuationAnalysis;
  $("#valuationDate").textContent = a ? `資料截至 ${a.as_of}` : "尚未同步";
  const items = [
    ["本益比 PE", formatNumber(a?.pe_ratio), a ? `${formatNumber(a.pe_percentile, 1)}% 分位` : "—"],
    ["股價淨值比 PB", formatNumber(a?.pb_ratio), a ? `${formatNumber(a.pb_percentile, 1)}% 分位` : "—"],
    ["現金殖利率", a?.dividend_yield == null ? "—" : `${formatNumber(a.dividend_yield)}%`, a ? `${formatNumber(a.dividend_yield_percentile, 1)}% 分位` : "—"],
    ["相對估值位置", a?.relative_valuation_band || "—", a ? `${a.observations} 個月樣本` : "—"],
  ];
  $("#valuationMetricGrid").innerHTML = items.map(([label, value, note]) => `
    <div class="valuation-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>
  `).join("");
}

function drawValuationChart() {
  const rows = state.valuations;
  const canvas = $("#valuationChart"), empty = $("#valuationChartEmpty");
  const usable = rows.filter(row => row.pe_ratio != null || row.pb_ratio != null);
  if (usable.length < 2) { empty.hidden = false; canvas.hidden = true; return; }
  empty.hidden = true; canvas.hidden = false;
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio; canvas.height = rect.height * ratio;
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const width = rect.width, height = rect.height, pad = { t: 14, r: 48, b: 30, l: 10 };
  const peValues = usable.map(row => row.pe_ratio).filter(value => value != null).map(Number);
  const pbValues = usable.map(row => row.pb_ratio).filter(value => value != null).map(Number);
  const peMax = Math.max(...peValues) * 1.12 || 1, pbMax = Math.max(...pbValues) * 1.12 || 1;
  const chartWidth = width - pad.l - pad.r, chartHeight = height - pad.t - pad.b;
  const x = index => pad.l + index / (usable.length - 1) * chartWidth;
  const yPe = value => pad.t + chartHeight - Number(value) / peMax * chartHeight;
  const yPb = value => pad.t + chartHeight - Number(value) / pbMax * chartHeight;
  ctx.font = "11px Segoe UI"; ctx.fillStyle = "#68736d"; ctx.strokeStyle = "#d9ddd7"; ctx.lineWidth = 1;
  for (let index = 0; index < 5; index++) {
    const y = pad.t + chartHeight * index / 4;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(width - pad.r, y); ctx.stroke();
    ctx.fillText(formatNumber(peMax * (4 - index) / 4, 0), width - pad.r + 8, y + 4);
  }
  const drawLine = (key, y, color) => {
    ctx.beginPath(); let started = false;
    usable.forEach((row, index) => {
      if (row[key] == null) return;
      if (started) ctx.lineTo(x(index), y(row[key])); else { ctx.moveTo(x(index), y(row[key])); started = true; }
    });
    ctx.strokeStyle = color; ctx.lineWidth = 2.2; ctx.stroke();
  };
  drawLine("pe_ratio", yPe, "#0d674b"); drawLine("pb_ratio", yPb, "#ad8138");
  ctx.fillStyle = "#68736d";
  ctx.fillText(usable[0].valuation_date, pad.l, height - 7);
  const end = usable.at(-1).valuation_date;
  ctx.fillText(end, width - pad.r - ctx.measureText(end).width, height - 7);
}

function renderFinancials() {
  const a = state.financialAnalysis;
  $("#financialPeriod").textContent = a ? `${a.fiscal_year} Q${a.fiscal_quarter}` : "尚未同步";
  const percent = value => value == null ? "—" : `${formatNumber(value)}%`;
  const items = [
    ["每股盈餘 EPS", formatNumber(a?.eps)],
    ["毛利率", percent(a?.gross_margin_percent)],
    ["營業利益率", percent(a?.operating_margin_percent)],
    ["淨利率", percent(a?.net_margin_percent)],
    ["年化 ROE", percent(a?.annualized_roe_percent)],
    ["負債比", percent(a?.debt_ratio_percent)],
    ["流動比率", percent(a?.current_ratio_percent)],
    ["每股淨值", formatNumber(a?.book_value_per_share)],
  ];
  $("#financialMetricGrid").innerHTML = items.map(([label, value]) => `
    <div class="financial-stat"><span>${label}</span><strong>${value}</strong></div>
  `).join("");
  $("#profitabilityNote").textContent = a
    ? `${a.profitability_status}｜報表類型 ${a.report_type.toUpperCase()}｜目前累積 ${a.observations} 季資料`
    : "同步最新財報後顯示獲利與財務結構。";
}

function renderDividends() {
  const rows = state.dividends;
  const latest = rows[0];
  $("#dividendSummary").innerHTML = latest ? `
    <div><span>最近除權息日</span><strong>${latest.ex_date}</strong></div>
    <div><span>每股現金股利</span><strong>${latest.cash_dividend == null ? "—" : formatNumber(latest.cash_dividend) + " 元"}</strong></div>
    <div><span>無償配股率</span><strong>${latest.stock_dividend_ratio == null ? "—" : formatNumber(latest.stock_dividend_ratio)}</strong></div>
  ` : '<div><span>目前狀態</span><strong>尚無公開除權息紀錄</strong></div>';
  $("#dividendTable").innerHTML = rows.length ? rows.map(row => `
    <tr><td>${row.ex_date}</td><td>${row.event_type}</td><td>${row.cash_dividend == null ? "—" : formatNumber(row.cash_dividend) + " 元"}</td><td>${formatNumber(row.stock_dividend_ratio)}</td></tr>
  `).join("") : '<tr><td colspan="4">官方預告表目前沒有這檔股票的資料</td></tr>';
}

async function syncDividends() {
  if (!state.stock) return;
  const button = $("#dividendSyncButton"), message = $("#dividendSyncMessage");
  setBusy(button, true, "正在更新…");
  try {
    const result = await api(`/dividends/sync?${new URLSearchParams({ symbol: state.stock.symbol })}`, { method: "POST" });
    message.textContent = `完成，共寫入 ${result.rows_written} 筆除權息事件。`;
    toast("股利與除權息資料已更新"); await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

function renderOwnership() {
  const data = state.ownership;
  if (!data) {
    $("#ownershipSummary").innerHTML = '<div><span>目前狀態</span><strong>尚無資料</strong></div>';
    $("#ownershipBar").innerHTML = "";
    $("#ownershipMeta").textContent = "同步後可查看持股集中或分散程度";
    $("#ownershipTable").innerHTML = '<tr><td colspan="4">尚未取得股權分散資料</td></tr>';
    return;
  }
  const groups = [
    ["小額持股 ≤20張", data.small, "small"],
    ["中型持股 20–200張", data.medium, "medium"],
    ["大額持股 >200張", data.large, "large"],
  ];
  $("#ownershipSummary").innerHTML = groups.map(([label, group]) => `
    <div><span>${label}</span><strong>${formatNumber(group.percentage)}%</strong><small>${formatNumber(group.holders, 0)} 個帳戶</small></div>
  `).join("");
  $("#ownershipBar").innerHTML = groups.map(([label, group, kind]) =>
    `<i class="${kind}" style="width:${Math.max(0, group.percentage)}%" title="${label} ${formatNumber(group.percentage)}%"></i>`
  ).join("");
  $("#ownershipMeta").innerHTML = `<strong>${data.concentration_label}</strong><span>資料日期 ${data.as_of} · 共 ${formatNumber(data.total_holders, 0)} 個帳戶</span>`;
  $("#ownershipTable").innerHTML = data.brackets.map(row => `
    <tr><td>${row.label}</td><td>${formatNumber(row.holders, 0)}</td><td>${formatNumber(row.shares, 0)}</td><td>${formatNumber(row.percentage)}%</td></tr>
  `).join("");
}

function sharesToLots(value) {
  return value == null ? "—" : formatNumber(Number(value) / 1000, 0);
}

function flowClass(value) {
  return Number(value) > 0 ? "positive-text" : Number(value) < 0 ? "negative-text" : "neutral-text";
}

function renderInstitutions() {
  const rows = state.institutions;
  const latest = rows.at(-1);
  $("#institutionSummary").innerHTML = latest ? `
    <article><span>外資買賣超</span><strong class="${flowClass(latest.foreign_net)}">${sharesToLots(latest.foreign_net)} 張</strong><small>買進 ${sharesToLots(latest.foreign_buy)}｜賣出 ${sharesToLots(latest.foreign_sell)}</small></article>
    <article><span>投信買賣超</span><strong class="${flowClass(latest.trust_net)}">${sharesToLots(latest.trust_net)} 張</strong><small>買進 ${sharesToLots(latest.trust_buy)}｜賣出 ${sharesToLots(latest.trust_sell)}｜${latest.trade_date}</small></article>
  ` : '<article><span>目前狀態</span><strong>尚無資料</strong><small>請更新法人資料</small></article>';
  $("#institutionTable").innerHTML = rows.length ? rows.slice(-20).reverse().map(row => `
    <tr><td>${row.trade_date}</td><td>${sharesToLots(row.foreign_buy)}</td><td>${sharesToLots(row.foreign_sell)}</td><td class="${flowClass(row.foreign_net)}">${sharesToLots(row.foreign_net)}</td><td>${sharesToLots(row.trust_buy)}</td><td>${sharesToLots(row.trust_sell)}</td><td class="${flowClass(row.trust_net)}">${sharesToLots(row.trust_net)}</td></tr>
  `).join("") : '<tr><td colspan="7">尚未取得法人資料</td></tr>';
}

async function syncInstitutions() {
  if (!state.stock) return;
  const button = $("#institutionSyncButton"), message = $("#institutionSyncMessage");
  setBusy(button, true, "正在更新…");
  try {
    const result = await api(`/institutions/sync?${new URLSearchParams({ symbol: state.stock.symbol })}`, { method: "POST" });
    message.textContent = `完成：${result.trade_date} 法人買賣資料。`;
    toast("外資與投信資料已更新"); await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function syncOwnership() {
  if (!state.stock) return;
  const button = $("#ownershipSyncButton"), message = $("#ownershipSyncMessage");
  setBusy(button, true, "正在更新…");
  try {
    const result = await api(`/ownership/sync?${new URLSearchParams({ symbol: state.stock.symbol })}`, { method: "POST" });
    message.textContent = `完成：${result.data_date}，寫入 ${result.rows_written} 個持股級距。`;
    toast("股權分散資料已更新"); await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

function renderQuote() {
  const prices = state.prices;
  if (!prices.length) {
    $("#latestClose").textContent = "—";
    $("#latestDate").textContent = "尚未載入行情";
    $("#priceChange").textContent = "—";
    return;
  }
  const latest = prices.at(-1);
  const previous = prices.at(-2);
  $("#latestClose").textContent = formatNumber(latest.close);
  $("#latestDate").textContent = `${latest.trade_date} 收盤`;
  const change = previous ? latest.close / previous.close - 1 : null;
  const el = $("#priceChange");
  el.textContent = formatPercent(change);
  el.className = change === null ? "neutral" : change >= 0 ? "positive" : "negative";
}

function renderAnalysis() {
  const a = state.analysis;
  $("#analysisDate").textContent = a ? `資料截至 ${a.as_of}` : "資料不足";
  const highDistance = a?.from_all_time_high;
  const highDistanceText = highDistance == null
    ? "—"
    : Math.abs(highDistance) < 0.0000001
      ? "目前為歷史新高"
      : `低於高點 ${Math.abs(highDistance * 100).toFixed(2)}%`;
  const metrics = [
    ["距歷史最高點", highDistanceText, a ? `最高收盤 ${formatNumber(a.all_time_high_close)}｜${a.all_time_high_date}` : "依已同步資料計算", false, true],
    ["5 日均線", a?.sma_5, "短期價格趨勢", false],
    ["20 日均線", a?.sma_20, "月度價格趨勢", false],
    ["60 日均線", a?.sma_60, "季線參考", false],
    ["RSI 14", a?.rsi_14, "動能強弱 0–100", false],
    ["5 日報酬", a?.return_5d, "近一週表現", true],
    ["20 日報酬", a?.return_20d, "近一月表現", true],
    ["年化波動", a?.volatility_20d_annualized, "20 日估算", true],
    ["量能比", a?.volume_ratio_20d, "相對 20 日均量", false],
  ];
  $("#metricGrid").innerHTML = metrics.map(([label, value, note, percent, textValue]) => `
    <div class="metric"><span>${label}</span><strong>${textValue ? value : percent ? formatPercent(value) : formatNumber(value)}</strong><small>${note}</small></div>
  `).join("");
}

function renderTechnicalIndicators() {
  const technical = state.technical;
  const grid = $("#technicalIndicatorGrid");
  const note = $("#technicalIndicatorNote");
  if (!technical) {
    grid.innerHTML = '<div class="technical-unavailable">技術指標資料不足或尚未同步。</div>';
    note.textContent = "資料不足不會被當成中性訊號。";
    return;
  }
  const values = technical.indicators || {};
  const labels = [
    ["SMA 20", "sma_20"], ["SMA 60", "sma_60"], ["RSI 14", "rsi_14"],
    ["MACD", "macd"], ["MACD signal", "macd_signal"], ["ATR 14", "atr_14"],
    ["Bollinger upper", "bollinger_upper"], ["Bollinger lower", "bollinger_lower"],
    ["ADX 14", "adx_14"], ["+DI 14", "plus_di_14"], ["-DI 14", "minus_di_14"],
    ["NATR 14", "natr_14"], ["MFI 14", "mfi_14"],
    ["Keltner upper", "keltner_upper_20"], ["Keltner lower", "keltner_lower_20"],
    ["Volume / 20d", "volume_ratio_20"], ["Distance to 60d high", "distance_to_60d_high_percent"],
    ["20d breakout", "breakout_20d"], ["Volume confirmed", "volume_confirmation_20d"],
    ["Trend confirmed", "trend_confirmation"],
  ];
  grid.innerHTML = labels.map(([label, key]) => {
    const value = values[key];
    const display = value === null || value === undefined ? "資料不足" :
      key === "distance_to_60d_high_percent" ? `${formatNumber(value)}%` : formatNumber(value);
    return `<div class="technical-indicator ${value == null ? "is-unavailable" : ""}"><span>${label}</span><strong>${display}</strong></div>`;
  }).join("");
  const available = Object.entries(technical.availability || {}).filter(([, value]) => value).map(([key]) => key);
  note.textContent = `資料截至 ${technical.as_of || "未知"}，使用 ${technical.input_rows || 0} 筆日資料；可用面向：${available.join("、") || "無"}。技術指標僅描述價格行為，並不保證未來報酬。`;
}

function renderShortTermAnalysis() {
  const target = $("#shortTermAnalysisContent");
  const report = state.shortTermAnalysis?.short_term_report;
  if (!report) {
    target.innerHTML = '<p class="dashboard-empty">短線分析需要至少 60 筆日 OHLCV 資料；目前不產生中性替代訊號。</p>';
    return;
  }
  const trend = report.trend || {};
  const levels = report.support_resistance || {};
  const indicators = report.indicators || {};
  const plan = report.trading_plan || {};
  const conclusion = report.plain_conclusion || {};
  const scenarios = report.scenarios || {};
  const market = state.shortTermAnalysis?.short_term_market || {};
  const number = value => value == null ? "資料不足" : formatNumber(value);
  const percent = value => value == null ? "資料不足" : `${formatNumber(value)}%`;
  const kd = indicators.kd || {};
  const bollinger = indicators.bollinger || {};
  const labels = {
    bullish: "偏多", bearish: "偏空", range_or_transition: "盤整／轉換中",
    higher_high_higher_low: "高點、低點墊高", lower_high_lower_low: "高點、低點下移", mixed_or_range: "結構混合／區間整理",
    strong: "強", moderate: "中等", weak: "弱", weak_or_mixed: "偏弱／訊號混合", elevated: "升高", contained: "受控", normal: "一般",
    confirmed: "量能確認", contracted: "量縮", neutral: "中性", long_upper_shadow: "長上影線", long_lower_shadow: "長下影線", doji: "十字線",
    bullish_engulfing: "多頭吞沒", bearish_engulfing: "空頭吞沒", bullish_body: "紅 K", bearish_body: "黑 K",
    selling_pressure_or_failed_chase_risk: "賣壓增加／追價失敗風險", support_test_requires_confirmation: "測試支撐，仍需確認",
    potential_reversal_requires_volume_and_structure_confirmation: "可能轉折，仍須量能與結構確認", single_candle_not_a_standalone_signal: "單一 K 線不足以單獨判斷",
    bullish_cross: "黃金交叉", bearish_cross: "死亡交叉", above_upper: "突破布林上軌", below_lower: "跌破布林下軌", inside_bands: "布林通道內",
    unavailable_no_intraday_data: "未提供正式分 K 資料", wait_for_confirmation: "等待確認", research_ready_if_confirmed: "確認條件後可研究",
    below_1_to_1_5_or_unavailable: "低於 1：1.5 或資料不足", meets_minimum_research_threshold: "達到研究門檻",
    daily_close_above_resistance_1_and_volume_at_least_1_2x_20d: "日收盤突破第一壓力，且成交量至少為 20 日均量 1.2 倍",
    close_above_resistance_1_with_volume_confirmation: "收盤突破第一壓力，且量能確認", price_remains_between_support_1_and_resistance_1: "價格持續在第一支撐與第一壓力間", daily_close_below_support_1: "日收盤跌破第一支撐",
    wait: "等待", trend_and_macd_conflict: "趨勢與 MACD 訊號衝突", trend_but_rsi_overbought: "趨勢偏多但 RSI 過熱",
  };
  const text = value => labels[value] || value || "資料不足";
  const actualRr = plan.cost_adjusted_risk_reward;
  const independentTarget = plan.planned_target;
  const requiredRr = plan.required_rr;
  const overextension = plan.overextension_check || {};
  const chaseControl = plan.trigger_checks?.chase_control || {};
  const meetsRr15 = actualRr != null && actualRr >= 1.5;
  const finalReasons = [];
  if (plan.reference_entry != null && plan.breakout_level != null && Number(plan.reference_entry) <= Number(plan.breakout_level)) finalReasons.push("尚未突破 20 日高點。");
  if (plan.mfi_check?.result === "偏熱") finalReasons.push(`MFI（${number(plan.mfi_check?.value)}）高於 ${number(plan.mfi_check?.hot_threshold)}，市場偏熱。`);
  if (plan.natr_check?.result === "過高") finalReasons.push(`NATR（${number(plan.natr_check?.value_percent)}%）高於 ${number(plan.natr_check?.high_threshold_percent)}%，波動過大。`);
  if (actualRr == null || requiredRr == null || Number(actualRr) < Number(requiredRr)) finalReasons.push(`若本策略設定最低 RR 為 1：${number(requiredRr)}，目前獨立推導目標的成本後 RR 僅有 1：${number(actualRr)}，不符合策略要求。`);
  if (!finalReasons.length && (plan.blocking_reasons || []).length) finalReasons.push(...plan.blocking_reasons);
  const overallReasons = conclusion.answer_code === "avoid" && (conclusion.missing_conditions || []).length
    ? conclusion.missing_conditions
    : finalReasons;
  const numberedReasons = overallReasons.map((reason, index) => `${"①②③④⑤⑥"[index] || `${index + 1}.`} ${reason}`).join("<br>");
  const conclusionClass = conclusion.answer_code === "conditional" ? "accumulate" : conclusion.answer_code === "avoid" ? "sell" : "wait";
  const conclusionReasons = conclusion.missing_conditions || [];
  const simpleReasons = conclusionReasons.join("；") === conclusion.summary
    ? ""
    : conclusionReasons.map(reason => `<li>${reason}</li>`).join("");
  const pricePlan = conclusion.reference_prices;
  const simplePricePlan = pricePlan ? `<div class="short-conclusion-prices"><span>最高進場 <strong>${number(pricePlan.maximum_entry)}</strong></span><span>停損參考 <strong>${number(pricePlan.stop)}</strong></span><span>目標參考 <strong>${number(pricePlan.target)}</strong></span><span>成本後 RR <strong>1：${number(pricePlan.cost_adjusted_rr)}</strong></span></div>` : "";
  const conclusionCard = `<article id="plainShortConclusion" class="dashboard-action-card short-conclusion-card ${conclusionClass}"><div><span class="short-conclusion-label">白話結論｜資料日 ${conclusion.data_date || report.as_of || "未知"}</span><strong>${conclusion.headline || "短線結論資料不足"}</strong><p>${conclusion.summary || "目前無法形成白話結論。"}</p>${simpleReasons ? `<ul>${simpleReasons}</ul>` : ""}${simplePricePlan}<small><b>接下來：</b>${conclusion.next_step || "等待資料更新。"}</small><small>${conclusion.scope || "只供短線技術研究，不保證報酬。"}</small></div></article>`;
  const rows = [
    ["一、趨勢", `短／中／長期：${trend.short || "資料不足"}／${trend.medium || "資料不足"}／${trend.long || "資料不足"}；價格結構：${trend.structure || "資料不足"}；趨勢強度：${trend.strength || "資料不足"}。MA5／10／20／60：${number(trend.moving_averages?.ma_5)}／${number(trend.moving_averages?.ma_10)}／${number(trend.moving_averages?.ma_20)}／${number(trend.moving_averages?.ma_60)}。`],
    ["二、支撐與壓力", `第一支撐 ${number(levels.support_1)}；第二支撐 ${number(levels.support_2)}；第一壓力 ${number(levels.resistance_1)}；第二壓力 ${number(levels.resistance_2)}。依據：MA20／MA60 或近期低點，以及前 20／55 日高點。`],
    ["三、成交量", `相對 20 日量 ${number(report.volume?.relative_to_20d)} 倍；狀態：${report.volume?.state || "資料不足"}；單日價格變動 ${percent(report.volume?.price_change_percent)}。量價確認不足時，不把突破視為成立。`],
    ["四、K 線", `最近型態：${report.candlestick?.pattern || "資料不足"}。解讀：${report.candlestick?.meaning || "資料不足"}。單一 K 線不會單獨觸發交易計畫。`],
    ["五、技術指標", `MACD：${indicators.macd_state || "資料不足"}（柱狀體 ${number(indicators.macd_histogram)}）；RSI14：${number(indicators.rsi_14)}；KD：K ${number(kd.k)}／D ${number(kd.d)}（${kd.signal || "資料不足"}）；布林：${bollinger.position || "資料不足"}。${(indicators.conflicts || []).length ? `衝突：${indicators.conflicts.join("、")}。` : "目前未偵測到此規則集定義的指標衝突。"}`],
    ["六、多週期", `日 K：${report.multi_timeframe?.daily || "資料不足"}；週 K：${report.multi_timeframe?.weekly || "資料不足"}；60 分鐘與 15 分鐘：目前沒有正式分 K 資料，因此不判斷。`],
    ["七、強弱評估", `多方：${report.strength?.bulls || "資料不足"}；空方：${report.strength?.bears || "資料不足"}；追價風險：${report.strength?.chase_risk || "資料不足"}。`],
    ["八、純技術交易評估", `此區只驗證技術計畫，不會覆蓋基本面門檻。<br>✓ 目前每股風險：${number(plan.math_verification?.risk)} 元<br>✓ 獨立推導目標：${number(independentTarget)} 元（${plan.planned_target_basis || "資料不足"}）<br>✓ 獨立目標的成本後風險報酬比：1：${number(actualRr)}<br>✓ 若策略要求最低 RR 為 1：1.5，本交易${meetsRr15 ? "符合" : "不符合"}。<br>${chaseControl.passed === false ? `✗ 追價控制未通過：短線漲幅與乖離過度延伸（5 日 ${percent(overextension.return_5d_percent)}；高於 MA5 ${percent(overextension.distance_to_sma5_percent)}；高於 MA20 ${percent(overextension.distance_to_sma20_percent)}）。` : "✓ 追價控制未偵測到複合過度延伸。"}<br>✓ 成本後最低 RR 所需價：${number(plan.minimum_target_required_rr_after_cost)} 元；此數字只是門檻，不是預測目標。<br>✓ 若毛 RR 為 1：2，目標至少需 ${number(plan.math_verification?.rr_2_target)} 元；若為 1：3，至少需 ${number(plan.math_verification?.rr_3_target)} 元。`],
    ["九、整體判定", `<strong>${conclusion.headline || plan.status || "資料不足"}</strong><br>原因：<br>${numberedReasons || "目前未偵測到固定規則的阻擋原因；開盤前仍須重算。"}`],
    ["十、計算依據", `大盤狀態：${market.mode || report.market_mode || "資料不足"}（市場分數 ${number(market.market_score)}、20 日指數變動 ${percent(market.index_change_20d)}），最低 RR 為 1：${number(requiredRr)}。參考進場 ${number(plan.reference_entry)}；最高允許進場 ${number(plan.maximum_entry_price)}，公式：${plan.maximum_entry_formula || "資料不足"}（ATR14 ${number(plan.maximum_entry_parameters?.atr_14)} × ${number(plan.maximum_entry_parameters?.chase_atr_multiple)}）。突破 K 棒低點 ${number(plan.stop_candidates?.breakout_candle_low)}；1.5 ATR 停損 ${number(plan.stop_candidates?.atr_1_5_stop)}；採用停損 ${number(plan.stop)}。MFI ${number(plan.mfi_check?.value)}／門檻 ${number(plan.mfi_check?.hot_threshold)}：${plan.mfi_check?.result || "資料不足"}；NATR ${number(plan.natr_check?.value_percent)}%／門檻 ${number(plan.natr_check?.high_threshold_percent)}%：${plan.natr_check?.result || "資料不足"}。`],
    ["十一、情境", `偏多：${scenarios.bullish?.condition || "資料不足"}，下一目標 ${number(scenarios.bullish?.next_target)}。中性：${scenarios.neutral?.condition || "資料不足"}，策略 ${scenarios.neutral?.action || "等待"}。偏空：${scenarios.bearish?.condition || "資料不足"}，下一支撐 ${number(scenarios.bearish?.next_support)}。`],
    ["十二、限制與風險", `資料日期 ${report.as_of || "未知"}。${(report.limitations || []).join(" ")} 技術分析不是報酬保證；消息、財報、政策、跳空與實際成交價格都可能改變結果。`],
  ];
  target.innerHTML = conclusionCard + rows.map(([title, detail]) => `<article class="dashboard-action-card wait"><div><strong>${title}</strong><small>${detail}</small></div></article>`).join("");
}

function renderShortPositionControl() {
  const button = $("#recordShortPositionButton");
  const status = $("#shortPositionStatus");
  const localEditing = ["127.0.0.1", "localhost", "::1"].includes(window.location.hostname);
  if (state.shortTermPosition) {
    const position = state.shortTermPosition;
    button.hidden = true;
    status.textContent = `已追蹤短線持倉｜剩餘 ${formatNumber(position.remaining_shares, 0)} 股｜${position.decision?.label || "每日檢查中"}`;
    return;
  }
  button.hidden = !localEditing;
  status.textContent = localEditing ? "3–10 個交易日研究｜可登記任何已買股票" : "3–10 個交易日研究｜公開頁面僅供查看";
}

function openIndividualPurchaseDialog() {
  if (!state.stock) return;
  const report = state.shortTermAnalysis?.short_term_report || {};
  const plan = report.trading_plan || {};
  const levels = report.support_resistance || {};
  const latest = state.prices.at(-1);
  const entry = Number(latest?.close);
  const stopCandidate = Number(plan.stop ?? levels.support_1);
  const targetCandidate = Number(plan.planned_target ?? levels.resistance_1);
  $("#individualPurchaseTitle").textContent = `登記 ${state.stock.symbol} ${state.stock.name} 的實際買進`;
  $("#individualEntryDate").value = localDate(new Date());
  $("#individualEntryPrice").value = Number.isFinite(entry) ? entry : "";
  $("#individualEntryShares").value = "1000";
  $("#individualStopPrice").value = Number.isFinite(stopCandidate) && (!Number.isFinite(entry) || stopCandidate < entry) ? stopCandidate : "";
  $("#individualTargetPrice").value = Number.isFinite(targetCandidate) && (!Number.isFinite(entry) || targetCandidate > entry) ? targetCandidate : "";
  const hasCompleteDefaults = $("#individualStopPrice").value && $("#individualTargetPrice").value;
  $("#individualPurchaseHint").textContent = hasCompleteDefaults
    ? "已帶入個股短線分析的停損與目標；請改成符合你實際交易計畫的數字。"
    : "目前沒有可直接採用的完整價位，請自行填寫低於買進價的停損，以及高於買進價的目標。";
  $("#individualPurchaseDialog").showModal();
}

async function saveIndividualShortPosition(event) {
  event.preventDefault();
  if (!state.stock) return;
  const payload = {
    symbol: state.stock.symbol,
    entry_date: $("#individualEntryDate").value,
    entry_price: Number($("#individualEntryPrice").value),
    shares: Number($("#individualEntryShares").value),
    stop_price: Number($("#individualStopPrice").value),
    target_price: Number($("#individualTargetPrice").value),
  };
  try {
    await api("/short-term-positions/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("#individualPurchaseDialog").close();
    toast("持倉已儲存，會和排行榜買進股票使用相同的賣出規則");
    await loadStock();
  } catch (error) { toast(error.message, true); }
}

function renderTable() {
  const rows = state.prices.slice(-10).reverse();
  $("#priceTable").innerHTML = rows.length ? rows.map(row => `
    <tr><td>${row.trade_date}</td><td>${formatNumber(row.open)}</td><td>${formatNumber(row.high)}</td><td>${formatNumber(row.low)}</td><td>${formatNumber(row.close)}</td><td>${formatNumber(row.volume, 0)}</td></tr>
  `).join("") : '<tr><td colspan="6">尚無行情資料</td></tr>';
}

let chartFrame;
function scheduleChartDraw() {
  cancelAnimationFrame(chartFrame);
  chartFrame = requestAnimationFrame(() => requestAnimationFrame(drawChart));
}

function drawChart() {
  const limit = Number($("#chartRange").value);
  const rows = state.prices.slice(-limit).filter(row =>
    [row.open, row.high, row.low, row.close, row.volume].every(value => Number.isFinite(Number(value)))
  );
  const canvas = $("#priceChart");
  const empty = $("#chartEmpty");
  if (rows.length < 2) { empty.hidden = false; canvas.hidden = true; return; }
  empty.hidden = true; canvas.hidden = false;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 10 || rect.height < 10) {
    chartFrame = requestAnimationFrame(drawChart);
    return;
  }
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  if ($("#chartMode").value === "candlestick") {
    $("#candlestickLegend").hidden = false;
    drawCandlesticks(ctx, rows, rect.width, rect.height);
    return;
  }
  $("#candlestickLegend").hidden = true;
  const width = rect.width, height = rect.height, pad = { t: 18, r: 62, b: 28, l: 8 };
  const values = rows.map(r => Number(r.close));
  let min = Math.min(...values), max = Math.max(...values);
  const margin = (max - min || 1) * .1; min -= margin; max += margin;
  const x = i => pad.l + i / (rows.length - 1) * (width - pad.l - pad.r);
  const y = value => pad.t + (max - value) / (max - min) * (height - pad.t - pad.b);
  ctx.font = "11px Segoe UI"; ctx.fillStyle = "#68736d"; ctx.strokeStyle = "#d9ddd7"; ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const value = min + (max - min) * i / 4, yy = y(value);
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(width - pad.r, yy); ctx.stroke();
    ctx.fillText(formatNumber(value), width - pad.r + 9, yy + 4);
  }
  const gradient = ctx.createLinearGradient(0, pad.t, 0, height - pad.b);
  gradient.addColorStop(0, "rgba(13,103,75,.24)"); gradient.addColorStop(1, "rgba(13,103,75,0)");
  ctx.beginPath(); rows.forEach((r, i) => i ? ctx.lineTo(x(i), y(r.close)) : ctx.moveTo(x(i), y(r.close)));
  ctx.lineTo(x(rows.length - 1), height - pad.b); ctx.lineTo(x(0), height - pad.b); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath(); rows.forEach((r, i) => i ? ctx.lineTo(x(i), y(r.close)) : ctx.moveTo(x(i), y(r.close)));
  ctx.strokeStyle = "#0d674b"; ctx.lineWidth = 2.2; ctx.stroke();
  ctx.fillStyle = "#68736d"; ctx.fillText(rows[0].trade_date, pad.l, height - 7);
  const endText = rows.at(-1).trade_date; ctx.fillText(endText, width - pad.r - ctx.measureText(endText).width, height - 7);
}

function drawCandlesticks(ctx, rows, width, height) {
  const pad = { t: 16, r: 62, b: 28, l: 8 };
  const volumeHeight = Math.max(48, height * .2);
  const gap = 16;
  const priceBottom = height - pad.b - volumeHeight - gap;
  const chartWidth = width - pad.l - pad.r;
  const highs = rows.map(row => Number(row.high));
  const lows = rows.map(row => Number(row.low));
  let min = Math.min(...lows), max = Math.max(...highs);
  const margin = (max - min || 1) * .06; min -= margin; max += margin;
  const priceHeight = priceBottom - pad.t;
  const y = value => pad.t + (max - Number(value)) / (max - min) * priceHeight;
  const slot = chartWidth / rows.length;
  const x = index => pad.l + (index + .5) * slot;
  const bodyWidth = Math.max(2, Math.min(11, slot * .72));
  const maxVolume = Math.max(...rows.map(row => Number(row.volume)), 1);
  const volumeTop = priceBottom + gap;
  const volumeBottom = height - pad.b;

  ctx.font = "11px Segoe UI"; ctx.fillStyle = "#68736d"; ctx.strokeStyle = "#d9ddd7"; ctx.lineWidth = 1;
  for (let index = 0; index < 5; index++) {
    const value = min + (max - min) * index / 4, yy = y(value);
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(width - pad.r, yy); ctx.stroke();
    ctx.fillText(formatNumber(value), width - pad.r + 9, yy + 4);
  }
  ctx.beginPath(); ctx.moveTo(pad.l, priceBottom + gap / 2); ctx.lineTo(width - pad.r, priceBottom + gap / 2); ctx.stroke();

  rows.forEach((row, index) => {
    const open = Number(row.open), close = Number(row.close), high = Number(row.high), low = Number(row.low);
    const rising = close >= open;
    const color = rising ? "#b33a3a" : "#0d674b";
    const center = x(index);
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = Math.max(1, Math.min(1.5, slot * .18));
    ctx.beginPath(); ctx.moveTo(center, y(high)); ctx.lineTo(center, y(low)); ctx.stroke();
    const top = y(Math.max(open, close)), bottom = y(Math.min(open, close));
    const bodyHeight = Math.max(1, bottom - top);
    if (rising && bodyWidth >= 2) {
      ctx.fillStyle = "#fffdf8"; ctx.fillRect(center - bodyWidth / 2, top, bodyWidth, bodyHeight);
      ctx.strokeRect(center - bodyWidth / 2, top, bodyWidth, bodyHeight);
    } else {
      ctx.fillStyle = color; ctx.fillRect(center - bodyWidth / 2, top, bodyWidth, bodyHeight);
    }
    const barHeight = Number(row.volume) / maxVolume * (volumeBottom - volumeTop);
    ctx.globalAlpha = .42; ctx.fillStyle = color;
    ctx.fillRect(center - bodyWidth / 2, volumeBottom - barHeight, bodyWidth, barHeight);
    ctx.globalAlpha = 1;
  });
  ctx.fillStyle = "#68736d";
  ctx.fillText(rows[0].trade_date, pad.l, height - 7);
  const endText = rows.at(-1).trade_date;
  ctx.fillText(endText, width - pad.r - ctx.measureText(endText).width, height - 7);
  ctx.fillText("成交量", pad.l, volumeTop + 10);
  const latest = rows.at(-1);
  const quote = `開 ${formatNumber(latest.open)}  高 ${formatNumber(latest.high)}  低 ${formatNumber(latest.low)}  收 ${formatNumber(latest.close)}`;
  ctx.fillStyle = "#26322d"; ctx.font = "600 11px Segoe UI";
  ctx.fillText(quote, pad.l + 4, pad.t + 12);
}

async function syncHistory() {
  if (!state.stock) return;
  const start = $("#startDate").value, end = $("#endDate").value;
  if (!start || !end) { toast("請選擇開始與結束日期", true); return; }
  const button = $("#historySyncButton");
  const message = $("#syncMessage");
  setBusy(button, true, "正在向官方取得資料…");
  message.textContent = "資料按月份同步，期間較長時請稍候。";
  try {
    const params = new URLSearchParams({ symbol: state.stock.symbol, start, end });
    const result = await api(`/history/sync?${params}`, { method: "POST" });
    message.textContent = `完成 ${result.months_completed} 個月份，共寫入 ${result.rows_written} 筆行情。`;
    toast("歷史行情同步完成");
    await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function syncRevenue() {
  if (!state.stock) return;
  const start = $("#revenueStart").value, end = $("#revenueEnd").value;
  if (!start || !end) { toast("請選擇月營收起訖月份", true); return; }
  const button = $("#revenueSyncButton"), message = $("#revenueSyncMessage");
  setBusy(button, true, "正在同步月營收…");
  message.textContent = "將逐月查詢公開資訊觀測站，請稍候。";
  try {
    const params = new URLSearchParams({ symbol: state.stock.symbol, start, end });
    const result = await api(`/revenue/sync?${params}`, { method: "POST" });
    message.textContent = `完成，共寫入 ${result.rows_written} 個月份。`;
    toast("月營收同步完成");
    await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function syncValuation() {
  if (!state.stock) return;
  const start = $("#valuationStart").value, end = $("#valuationEnd").value;
  if (!start || !end) { toast("請選擇估值起訖月份", true); return; }
  const button = $("#valuationSyncButton"), message = $("#valuationSyncMessage");
  setBusy(button, true, "正在同步估值…");
  message.textContent = "每月取最近交易日資料，休市日會自動往前尋找。";
  try {
    const params = new URLSearchParams({ symbol: state.stock.symbol, start, end });
    const result = await api(`/valuation/sync?${params}`, { method: "POST" });
    message.textContent = `完成，共寫入 ${result.rows_written} 個月份。`;
    toast("估值資料同步完成"); await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function syncFinancials() {
  if (!state.stock) return;
  const button = $("#financialSyncButton"), message = $("#financialSyncMessage");
  setBusy(button, true, "正在同步季報…");
  message.textContent = "正在辨識產業報表類型並整合損益表與資產負債表。";
  try {
    const params = new URLSearchParams({ symbol: state.stock.symbol });
    const result = await api(`/financials/sync?${params}`, { method: "POST" });
    message.textContent = `完成：${result.fiscal_year} Q${result.fiscal_quarter}`;
    toast("最新財報同步完成"); await loadStock();
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

const today = new Date();
const threeYearsAgo = new Date(today); threeYearsAgo.setFullYear(today.getFullYear() - 3);
$("#endDate").value = today.toISOString().slice(0, 10);
$("#startDate").value = threeYearsAgo.toISOString().slice(0, 10);
$("#revenueEnd").value = today.toISOString().slice(0, 7);
$("#revenueStart").value = threeYearsAgo.toISOString().slice(0, 7);
$("#valuationEnd").value = today.toISOString().slice(0, 7);
$("#valuationStart").value = threeYearsAgo.toISOString().slice(0, 7);
$("#marketSyncButton").addEventListener("click", syncMarket);
$("#searchButton").addEventListener("click", searchStocks);
$("#stockSearch").addEventListener("keydown", event => { if (event.key === "Enter") searchStocks(); });
$("#historySyncButton").addEventListener("click", syncHistory);
$("#revenueSyncButton").addEventListener("click", syncRevenue);
$("#valuationSyncButton").addEventListener("click", syncValuation);
$("#financialSyncButton").addEventListener("click", syncFinancials);
$("#dividendSyncButton").addEventListener("click", syncDividends);
$("#ownershipSyncButton").addEventListener("click", syncOwnership);
$("#institutionSyncButton").addEventListener("click", syncInstitutions);
$("#watchlistButton").addEventListener("click", toggleWatchlist);
$("#recordShortPositionButton").addEventListener("click", openIndividualPurchaseDialog);
$("#individualPurchaseForm").addEventListener("submit", saveIndividualShortPosition);
$("#closeIndividualPurchaseDialog").addEventListener("click", () => $("#individualPurchaseDialog").close());
$("#cancelIndividualPurchase").addEventListener("click", () => $("#individualPurchaseDialog").close());
$("#chartRange").addEventListener("change", scheduleChartDraw);
$("#chartMode").addEventListener("change", scheduleChartDraw);
window.addEventListener("resize", () => {
  if (state.prices.length) scheduleChartDraw();
  if (state.revenues.length) drawRevenueChart();
  if (state.valuations.length) drawValuationChart();
});
if ("ResizeObserver" in window) {
  new ResizeObserver(() => { if (state.prices.length) scheduleChartDraw(); }).observe($("#priceChart").parentElement);
}
checkHealth();
openStockFromUrl();
