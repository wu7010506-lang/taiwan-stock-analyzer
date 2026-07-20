const $ = selector => document.querySelector(selector);
let toastTimer;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) throw new Error(payload?.detail || `請求失敗（${response.status}）`);
  return payload;
}

function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = "toast", 3200);
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

function formatGrowth(value) {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}
function formatMoney(value) {
  if (value == null) return "—";
  return Number(value) >= 100000000 ? `${formatNumber(Number(value) / 100000000)} 億` : `${formatNumber(Number(value) / 10000)} 萬`;
}

const fields = {
  market: "#filterMarket", industry: "#filterIndustry",
  min_revenue_yoy: "#filterRevenueYoy", min_gross_margin: "#filterGrossMargin",
  min_roe: "#filterRoe", max_debt_ratio: "#filterDebt", max_pe: "#filterPe",
  min_dividend_yield: "#filterYield", min_rsi: "#filterRsiMin",
  max_rsi: "#filterRsiMax", above_sma60: "#filterSma", sort_by: "#filterSort",
};

function query() {
  const params = new URLSearchParams({ limit: "3000", descending: "true" });
  params.set("popular_only", String($("#filterPopular").checked));
  params.set("ai_theme", String($("#filterAiTheme").checked));
  params.set("defense_drone_theme", String($("#filterDefenseTheme").checked));
  params.set("ic_design_theme", String($("#filterIcDesignTheme").checked));
  Object.entries(fields).forEach(([name, selector]) => {
    const value = $(selector).value.trim();
    if (value !== "") params.set(name, value);
  });
  return params;
}

async function syncUniverse() {
  const button = $("#screenerSyncButton"), message = $("#screenerMessage");
  setBusy(button, true, "正在建立資料集…");
  message.textContent = "同步全市場月營收、估值與最新季報，約需數十秒。";
  try {
    const result = await api("/screener/sync", { method: "POST" });
    message.textContent = `完成：營收 ${result.revenues}、估值 ${result.valuations}、財報 ${result.financials} 筆`;
    toast("全市場選股資料已更新");
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

async function run() {
  const button = $("#runScreenerButton"), message = $("#screenerMessage");
  setBusy(button, true, "篩選中…");
  try {
    const rows = await api(`/screener?${query()}`);
    const technical = $("#filterSma").value || $("#filterRsiMin").value || $("#filterRsiMax").value;
    message.textContent = rows.length ? `找到 ${rows.length} 檔符合條件的股票`
      : technical ? "沒有結果：RSI 或季線條件需要足夠歷史行情。"
      : "沒有結果：請清除全部條件後重試，再逐項加入條件。";
    const body = $("#screenerTable");
    body.innerHTML = rows.length ? rows.map((row, index) => `
      <tr data-index="${index}"><td><strong>${row.symbol}</strong> ${row.name}<small>${row.market}</small></td><td>${row.themes.length ? row.themes.map(theme => `<span class="theme-tag">${theme}</span>`).join("") : "—"}</td><td>${row.popular_rank ? `#${row.popular_rank}` : "—"}</td><td>${formatMoney(row.turnover)}</td><td>${formatGrowth(row.revenue_yoy)}</td><td>${formatGrowth(row.roe)}</td><td>${formatNumber(row.pe)}</td><td>${row.dividend_yield == null ? "—" : formatNumber(row.dividend_yield) + "%"}</td><td>${row.completeness}%</td></tr>
    `).join("") : '<tr><td colspan="9">沒有符合目前條件的股票</td></tr>';
    body.querySelectorAll("tr[data-index]").forEach(tr => tr.addEventListener("click", () => {
      window.location.href = `/?symbol=${encodeURIComponent(rows[Number(tr.dataset.index)].symbol)}`;
    }));
  } catch (error) { message.textContent = error.message; toast(error.message, true); }
  finally { setBusy(button, false); }
}

function reset() {
  Object.values(fields).forEach(selector => {
    const field = $(selector);
    field.value = field.id === "filterSort" ? "completeness" : "";
  });
  $("#filterPopular").checked = false;
  ["#filterAiTheme", "#filterDefenseTheme", "#filterIcDesignTheme"].forEach(selector => $(selector).checked = false);
  $("#screenerMessage").textContent = "條件已清除；按「開始選股」查看資料最完整的股票。";
}

async function checkHealth() {
  const el = $("#apiStatus");
  try { await api("/health"); el.className = "status-dot online"; el.innerHTML = "<i></i>服務正常"; }
  catch { el.className = "status-dot offline"; el.innerHTML = "<i></i>服務中斷"; }
}

$("#screenerSyncButton").addEventListener("click", syncUniverse);
$("#runScreenerButton").addEventListener("click", run);
$("#resetScreenerButton").addEventListener("click", reset);
$("#exportScreenerButton").addEventListener("click", () => window.location.href = `/screener/export?${query()}`);
checkHealth();
run();
