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
  toastTimer = setTimeout(() => el.className = "toast", 3000);
}

function number(value) {
  return value == null ? "—" : Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

function percent(value) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
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
    const rows = await api("/watchlist");
    $("#watchlistSummary").textContent = `目前觀察 ${rows.length} 檔股票`;
    $("#watchlistEmpty").classList.toggle("hidden", rows.length > 0);
    const grid = $("#watchlistGrid");
    grid.hidden = rows.length === 0;
    grid.innerHTML = rows.map(row => {
      const changeClass = row.change_percent == null ? "neutral-text" : row.change_percent >= 0 ? "positive-text" : "negative-text";
      const highText = row.from_all_time_high == null ? "尚無歷史行情" : Math.abs(row.from_all_time_high) < .0000001 ? "目前為歷史新高" : `距高點 ${(Math.abs(row.from_all_time_high) * 100).toFixed(2)}%`;
      return `<article class="watch-card" data-symbol="${row.symbol}" tabindex="0" role="link">
        <div class="watch-card-head"><div><span>${row.market}</span><h2>${row.symbol} ${row.name}</h2></div><button class="remove-watch" data-symbol="${row.symbol}" type="button" aria-label="移除 ${row.name}">移除</button></div>
        <div class="watch-quote"><strong>${number(row.close)}</strong><span class="${changeClass}">${percent(row.change_percent)}</span></div>
        <div class="watch-meta"><span>${row.trade_date || "尚無行情日期"}</span><span>${highText}</span></div>
      </article>`;
    }).join("");
    grid.querySelectorAll(".watch-card").forEach(card => {
      const open = () => window.location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
      card.addEventListener("click", open);
      card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    });
    grid.querySelectorAll(".remove-watch").forEach(button => button.addEventListener("click", event => removeStock(event, button.dataset.symbol)));
  } catch (error) { $("#watchlistSummary").textContent = error.message; toast(error.message, true); }
}

async function checkHealth() {
  const el = $("#apiStatus");
  try { await api("/health"); el.className = "status-dot online"; el.innerHTML = "<i></i>服務正常"; }
  catch { el.className = "status-dot offline"; el.innerHTML = "<i></i>服務中斷"; }
}

checkHealth();
load();
