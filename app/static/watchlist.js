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
        <button class="edit-position button secondary" data-symbol="${row.symbol}" type="button">${row.is_held ? "編輯持倉與風險" : "新增持倉"}</button>
      </article>`;
    }).join("");
    grid.querySelectorAll(".watch-card").forEach(card => {
      const open = () => window.location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
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
