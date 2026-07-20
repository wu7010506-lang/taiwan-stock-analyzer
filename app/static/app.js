const $ = (selector) => document.querySelector(selector);
const state = {
  stock: null, prices: [], analysis: null, revenues: [], revenueAnalysis: null,
  valuations: [], valuationAnalysis: null, financials: [], financialAnalysis: null,
  dividends: [], ownership: null, institutions: [], company: null, score: null,
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

  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setFullYear(startDate.getFullYear() - 1);
  const start = localDate(startDate);
  const end = localDate(endDate);
  const startMonth = start.slice(0, 7);
  const endMonth = end.slice(0, 7);
  const messages = ["#syncMessage", "#revenueSyncMessage", "#valuationSyncMessage", "#financialSyncMessage", "#dividendSyncMessage", "#ownershipSyncMessage", "#institutionSyncMessage"];
  messages.forEach(selector => $(selector).textContent = "選取股票後自動同步中…");
  toast("正在自動更新近 1 年資料…");

  const requests = [
    api(`/history/sync?${new URLSearchParams({ symbol, start, end })}`, { method: "POST" }),
    api(`/revenue/sync?${new URLSearchParams({ symbol, start: startMonth, end: endMonth })}`, { method: "POST" }),
    api(`/valuation/sync?${new URLSearchParams({ symbol, start: startMonth, end: endMonth })}`, { method: "POST" }),
    api(`/financials/sync?${new URLSearchParams({ symbol })}`, { method: "POST" }),
    api(`/dividends/sync?${new URLSearchParams({ symbol })}`, { method: "POST" }),
    api(`/ownership/sync?${new URLSearchParams({ symbol })}`, { method: "POST" }),
    api(`/institutions/sync?${new URLSearchParams({ symbol })}`, { method: "POST" }),
  ];
  const results = await Promise.allSettled(requests);
  const labels = ["行情", "營收", "估值", "財報", "股利與除權息", "股權分散", "法人買賣"];
  const succeeded = results.filter(result => result.status === "fulfilled").length;
  results.forEach((result, index) => {
    $(messages[index]).textContent = result.status === "fulfilled"
      ? `自動同步完成（近 1 年${labels[index]}）`
      : `自動同步未完成：${result.reason.message}`;
  });
  if (state.stock?.symbol !== symbol) return;
  await loadStock();
  const failed = labels.length - succeeded;
  toast(failed ? `自動更新完成 ${succeeded} 項，${failed} 項未完成` : "近 1 年資料已自動更新", failed > 0);
}

async function loadStock() {
  const symbol = state.stock.symbol;
  try {
    const [prices, analysis, revenues, revenueAnalysis, valuations, valuationAnalysis, financials, financialAnalysis, dividends, ownership, institutions, company, score] = await Promise.all([
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
    renderQuote();
    renderAnalysis();
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
