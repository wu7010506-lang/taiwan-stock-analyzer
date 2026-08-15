const $ = selector => document.querySelector(selector);
let toastTimer;
let watchRows = new Map();

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
  toastTimer = setTimeout(() => el.className = "toast", 3000);
}

function number(value) {
  return value == null ? "—" : Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function percent(value) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}
function money(value) { return value == null ? "—" : `NT$ ${Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 0 })}`; }
function nullableNumber(selector) { const value = $(selector).value; return value === "" ? null : Number(value); }

const decisionLabel = {
  add: "\u52a0\u78bc", hold: "\u7e7c\u7e8c\u6301\u6709", wait: "\u89c0\u671b",
  build_small: "\u5c0f\u984d\u5206\u6279", short_history_watch: "\u8cc7\u6599\u8f03\u77ed\u89c0\u5bdf", short_history_build: "\u8cc7\u6599\u8f03\u77ed\u8a66\u55ae", reduce: "\u6e1b\u78bc", sell: "\u8ce3\u51fa", insufficient_data: "\u8cc7\u6599\u4e0d\u8db3",
};
const decisionReason = {
  stop_loss_triggered: "\u5df2\u89f8\u767c\u505c\u640d\u50f9", target_price_reached: "\u5df2\u5230\u9054\u76ee\u6a19\u50f9",
  single_stock_limit_exceeded: "\u55ae\u4e00\u6301\u80a1\u8d85\u904e 10% \u98a8\u96aa\u4e0a\u9650",
  insufficient_vnext_data: "\u65b0\u6a21\u578b\u8cc7\u6599\u5c1a\u4e0d\u8db3", durable_business_quality: "\u4f01\u696d\u54c1\u8cea\u7a69\u5065",
  cashflow_supports_earnings: "\u73fe\u91d1\u6d41\u652f\u6490\u7372\u5229", valuation_has_margin_of_safety: "\u4f30\u503c\u5177\u5b89\u5168\u908a\u969b",
  market_risk_off: "\u5e02\u5834\u8655\u65bc\u98a8\u96aa\u8da8\u907f\u72c0\u614b", institution_driven_surge: "\u6cd5\u4eba\u8ffd\u50f9\u98a8\u96aa\u504f\u9ad8",
  risk_off_quality_candidate: "\u504f\u7a7a\u5e02\u5834\u4e2d\u7684\u9ad8\u54c1\u8cea\u5206\u6279\u5019\u9078",
  entry_plan_not_confirmed: "\u9032\u5834\u5340\u3001\u91cf\u80fd\u6216\u98a8\u96aa\u9810\u7b97\u5c1a\u672a\u78ba\u8a8d\uff0c\u5148\u89c0\u671b",
  short_history_model: "\u4ee5\u8fd1\u671f\u8ca1\u5831\u8207\u884c\u60c5\u9032\u884c\u8f03\u77ed\u8cc7\u6599\u8a55\u4f30", recent_financials_available: "\u8fd1\u671f\u8ca1\u5831\u53ef\u4f9b\u5206\u6790",
  limited_operating_history: "\u71df\u904b\u6b77\u53f2\u5c1a\u77ed\uff0c\u4e0d\u53ef\u8996\u70ba\u9577\u671f\u54c1\u8cea\u8b49\u660e",
};

function renderDecision(decision) {
  if (!decision) return "";
  const reasons = [...(decision.reasons || []), ...(decision.risks || [])]
    .map(item => decisionReason[item] || item).slice(0, 3);
  const plan = decision.entry_plan;
  const checklist = decision.investment_checklist;
  const planHtml = plan?.entry_zone ? `<div class="entry-plan"><small>\u9032\u5834\u8a08\u756b\uff08\u7814\u7a76\u7528\u9014\uff09</small><span>\u5340\u9593 ${number(plan.entry_zone.low)}–${number(plan.entry_zone.high)}\uff5c\u5931\u6548 ${number(plan.invalidation_price)}</span><span>\u98a8\u96aa ${number(plan.risk_percent)}%\uff5c\u521d\u59cb\u90e8\u4f4d\u4e0a\u9650 ${number(plan.suggested_initial_position_percent)}%</span></div>` : `<small>\u9032\u5834\u8a08\u756b\u8cc7\u6599\u4e0d\u8db3\uff0c\u8acb\u5148\u540c\u6b65\u8fd1\u671f\u50f9\u91cf\u8cc7\u6599\u3002</small>`;
  const checklistHtml = checklist ? `<small>\u81ea\u52d5\u6aa2\u6838\u901a\u904e ${checklist.passed}/${checklist.total}\uff1b\u5546\u696d\u6a21\u5f0f\u3001\u6cbb\u7406\u8207\u8ad6\u9ede\u5931\u6548\u689d\u4ef6\u4ecd\u9808\u4eba\u5de5\u7814\u7a76\u3002</small>` : "";
  return `<section class="position-decision ${decision.action}">
    <div><span>\u76e4\u52e2\u7d9c\u5408\u5efa\u8b70</span><strong>${decisionLabel[decision.action] || decision.action}</strong></div>
    ${decision.value_score != null ? `<small>\u4f01\u696d\u50f9\u503c ${number(decision.value_score)} \uff5c\u9032\u5834\u6642\u6a5f ${number(decision.timing_score)}</small>` : ""}
    ${decision.new_allocation_percent > 0 ? `<small>\u5efa\u8b70\u6700\u591a\u52a0\u78bc ${number(decision.new_allocation_percent)}% \u7e3d\u8cc7\u91d1</small>` : ""}
    ${reasons.length ? `<ul>${reasons.map(item => `<li>${item}</li>`).join("")}</ul>` : ""}
    ${planHtml}${checklistHtml}
  </section>`;
}

function renderPortfolio(data) {
  $("#portfolioSummary").innerHTML = `<article><span>持有股票</span><strong>${data.held_count}</strong><small>觀察 ${data.watching_count} 檔</small></article><article><span>投入成本</span><strong>${money(data.total_cost)}</strong></article><article><span>目前市值</span><strong>${money(data.total_market_value)}</strong></article><article><span>未實現損益</span><strong class="${data.unrealized_profit >= 0 ? "positive-text" : "negative-text"}">${money(data.unrealized_profit)}</strong><small>${data.unrealized_return_percent == null ? "—" : `${data.unrealized_return_percent >= 0 ? "+" : ""}${number(data.unrealized_return_percent)}%`}</small></article><article><span>最大單一部位</span><strong>${number(data.largest_position_percent)}%</strong></article>`;
  $("#industryExposure").innerHTML = data.industry_exposure.map(item => `<div><span>${item.industry}</span><i><b style="width:${Math.min(item.weight_percent, 100)}%"></b></i><strong>${number(item.weight_percent)}%</strong></div>`).join("") || `<p class="muted">輸入持倉後顯示產業配置。</p>`;
  $("#portfolioWarnings").innerHTML = data.warnings.map(item => `<li>${item}</li>`).join("") || `<li class="safe">目前沒有觸發集中度、停損或目標價提醒。</li>`;
}

function openPosition(symbol) {
  const row = watchRows.get(symbol); if (!row) return;
  $("#positionSymbol").value = symbol; $("#positionTitle").textContent = `編輯 ${symbol} ${row.name} 持倉`;
  $("#averageCost").value = row.average_cost ?? ""; $("#positionShares").value = row.shares ?? "";
  $("#purchaseDate").value = row.purchase_date ?? ""; $("#investmentHorizon").value = row.investment_horizon ?? "";
  $("#stopLoss").value = row.stop_loss ?? ""; $("#targetPrice").value = row.target_price ?? ""; $("#positionNotes").value = row.notes ?? "";
  $("#positionDialog").showModal();
}

async function removeStock(event, symbol) {
  event.preventDefault();
  event.stopPropagation();
  try {
    await api(`/watchlist/${symbol}`, { method: "DELETE" });
    toast("已從我的股票移除");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function load() {
  try {
    const [rows, portfolio] = await Promise.all([api("/watchlist"), api("/portfolio/summary")]);
    watchRows = new Map(rows.map(row => [row.symbol, row])); renderPortfolio(portfolio);
    const portfolioDecisions = new Map([
      ...(portfolio.positions || []).map(item => [item.symbol, item.portfolio_decision]),
      ...(portfolio.watching_decisions || []).map(item => [item.symbol, item.decision]),
    ]);
    $("#watchlistSummary").textContent = `目前觀察 ${rows.length} 檔股票，其中 ${portfolio.held_count} 檔已輸入持倉`;
    $("#watchlistEmpty").classList.toggle("hidden", rows.length > 0);
    const grid = $("#watchlistGrid");
    grid.hidden = rows.length === 0;
    grid.innerHTML = rows.map(row => {
      const changeClass = row.change_percent == null ? "neutral-text" : row.change_percent >= 0 ? "positive-text" : "negative-text";
      const highText = row.from_all_time_high == null ? "尚無歷史行情" : Math.abs(row.from_all_time_high) < .0000001 ? "目前為歷史新高" : `距高點 ${(Math.abs(row.from_all_time_high) * 100).toFixed(2)}%`;
      return `<article class="watch-card" data-symbol="${row.symbol}" tabindex="0" role="link">
        <div class="watch-card-head"><div><span>${row.market}</span><h2>${row.symbol} ${row.name}</h2></div><button class="remove-watch" data-symbol="${row.symbol}" type="button" aria-label="移除 ${row.name}">移除</button></div>
        <div class="watch-quote"><strong>${number(row.close)}</strong><span class="${changeClass}">${percent(row.change_percent)}</span></div>
        <div class="watch-meta"><span>${row.trade_date ? (row.quote_is_current ? row.trade_date : `最後成交 ${row.trade_date}（尚未取得 ${row.market_latest_date} 行情）`) : "尚無行情日期"}</span><span>${highText}</span></div>
        ${row.is_held ? `<div class="position-brief"><div><span>平均成本</span><strong>${number(row.average_cost)}</strong></div><div><span>持有</span><strong>${number(row.shares)} 股</strong></div><div><span>市值</span><strong>${money(row.market_value)}</strong></div><div><span>未實現損益</span><strong class="${row.unrealized_profit >= 0 ? "positive-text" : "negative-text"}">${money(row.unrealized_profit)}<small>${percent(row.unrealized_return)}</small></strong></div></div>` : `<p class="position-empty">尚未輸入持倉，可作為純觀察股票。</p>`}
        ${renderDecision(portfolioDecisions.get(row.symbol))}
        <button class="edit-position button secondary" data-symbol="${row.symbol}" type="button">${row.is_held ? "編輯持倉與風險" : "新增持倉"}</button>
      </article>`;
    }).join("");
    grid.querySelectorAll(".watch-card").forEach(card => {
      const open = () => window.location.href = `/stock/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
      card.addEventListener("click", open);
      card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    });
    grid.querySelectorAll(".remove-watch").forEach(button => button.addEventListener("click", event => removeStock(event, button.dataset.symbol)));
    grid.querySelectorAll(".edit-position").forEach(button => button.addEventListener("click", event => { event.stopPropagation(); openPosition(button.dataset.symbol); }));
  } catch (error) { $("#watchlistSummary").textContent = error.message; toast(error.message, true); }
}

$("#closePositionDialog").addEventListener("click", () => $("#positionDialog").close());
$("#positionForm").addEventListener("submit", async event => {
  event.preventDefault();
  const symbol = $("#positionSymbol").value;
  const payload = { average_cost: nullableNumber("#averageCost"), shares: nullableNumber("#positionShares"), purchase_date: $("#purchaseDate").value || null, stop_loss: nullableNumber("#stopLoss"), target_price: nullableNumber("#targetPrice"), investment_horizon: $("#investmentHorizon").value || null, notes: $("#positionNotes").value.trim() || null };
  try { await api(`/watchlist/${symbol}/position`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); $("#positionDialog").close(); toast("持倉與風險設定已儲存"); await load(); } catch (error) { toast(error.message, true); }
});
$("#clearPositionButton").addEventListener("click", async () => {
  const symbol = $("#positionSymbol").value;
  try { await api(`/watchlist/${symbol}/position`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shares: 0 }) }); $("#positionDialog").close(); toast("已清除持倉資料，股票仍保留在觀察清單"); await load(); } catch (error) { toast(error.message, true); }
});

async function checkHealth() {
  const el = $("#apiStatus");
  try { await api("/health"); el.className = "status-dot online"; el.innerHTML = "<i></i>服務正常"; }
  catch { el.className = "status-dot offline"; el.innerHTML = "<i></i>服務中斷"; }
}

checkHealth();
load();
