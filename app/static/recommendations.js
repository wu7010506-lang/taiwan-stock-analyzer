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
  const el = $("#toast"); el.textContent = message; el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.className = "toast", 3200);
}
function number(value) { return value == null ? "—" : Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 }); }
function growth(value) { return value == null ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`; }
function money(value) {
  if (value == null) return "—";
  const amount = Number(value);
  return amount >= 100000000 ? `${number(amount / 100000000)} 億` : `${number(amount / 10000)} 萬`;
}
function lots(value) { return value == null ? "—" : `${number(Number(value) / 1000)} 張`; }

const profiles = {
  balanced: { title: "綜合多因子", weights: "品質 40｜成長 25｜估值 25｜資料 10", rule: "平衡品質、成長與估值，只納入資料完整度至少 70% 的公司。" },
  value: { title: "價值型", weights: "品質 25｜成長 10｜估值 55｜資料 10", rule: "硬性條件：EPS 為正、PE＜15、PB＜2、負債比不高於 70%。" },
  growth: { title: "成長型", weights: "品質 25｜成長 50｜估值 15｜資料 10", rule: "硬性條件：EPS 為正、營收年增至少 20%、ROE 為正。" },
  quality: { title: "品質型", weights: "品質 55｜成長 20｜估值 15｜資料 10", rule: "硬性條件：EPS 為正、ROE 至少 10%、毛利率為正、負債比不高於 60%。" },
};

function updateMethod() {
  const method = profiles[$("#recommendationProfile").value];
  $("#methodTitle").textContent = method.title; $("#methodWeights").textContent = method.weights; $("#methodRule").textContent = method.rule;
}

async function addWatch(event, symbol) {
  event.stopPropagation();
  const button = event.currentTarget; button.disabled = true;
  try { await api(`/watchlist/${symbol}`, { method: "PUT" }); button.textContent = "✓ 已加入"; toast("已加入我的股票"); }
  catch (error) { toast(error.message, true); button.disabled = false; }
}

async function loadRecommendations() {
  const status = $("#recommendationStatus"); status.textContent = "正在依最新資料評分…";
  try {
    const profile = $("#recommendationProfile").value;
    const rows = await api(`/recommendations?limit=24&min_completeness=70&profile=${profile}`);
    status.textContent = rows.length ? `顯示 ${rows.length} 檔基本面研究候選；分數為市場相對排名` : "沒有足夠完整的資料";
    $("#recommendationEmpty").classList.toggle("hidden", rows.length > 0);
    const grid = $("#recommendationGrid"); grid.hidden = rows.length === 0;
    grid.innerHTML = rows.map((row, index) => `
      <article class="recommendation-card" data-symbol="${row.symbol}" tabindex="0" role="link">
        <div class="recommendation-rank">#${index + 1}</div>
        <div class="recommendation-head"><div><span>${row.rating}</span><h2>${row.symbol} ${row.name}</h2><small>${row.market} · ${row.industry || "產業未分類"}</small></div><strong>${number(row.score)}<i>分</i></strong></div>
        <div class="score-bar"><i style="width:${Math.min(row.score, 100)}%"></i></div>
        <div class="factor-grid"><span>品質<strong>${number(row.quality_score)}/40</strong></span><span>成長<strong>${number(row.growth_score)}/25</strong></span><span>估值<strong>${number(row.value_score)}/25</strong></span><span>資料<strong>${row.completeness}%</strong></span></div>
        <ul class="reason-list">${row.reasons.map(reason => `<li>${reason}</li>`).join("")}</ul>
        ${row.risks.length ? `<div class="risk-note">注意：${row.risks.join("、")}</div>` : ""}
        <div class="recommendation-footer"><span>PE ${number(row.pe)} · ROE ${growth(row.roe)} · 營收 ${growth(row.revenue_yoy)}</span><button class="quick-watch" data-symbol="${row.symbol}" type="button">＋ 我的股票</button></div>
      </article>`).join("");
    grid.querySelectorAll(".recommendation-card").forEach(card => {
      const open = () => window.location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
      card.addEventListener("click", open); card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    });
    grid.querySelectorAll(".quick-watch").forEach(button => button.addEventListener("click", event => addWatch(event, button.dataset.symbol)));
  } catch (error) { status.textContent = error.message; toast(error.message, true); }
}

async function loadPopularStocks() {
  const status = $("#popularStatus"); status.textContent = "正在整理最新市場熱度…";
  try {
    const rows = await api("/popular-stocks?limit=12");
    status.textContent = rows.length ? `資料日期 ${rows[0].trade_date}｜依成交金額排序` : "尚無全市場行情，請更新熱門排行";
    $("#popularGrid").innerHTML = rows.map((row, index) => `
      <article class="popular-card" data-symbol="${row.symbol}" tabindex="0" role="link">
        <span class="popular-rank">${String(index + 1).padStart(2, "0")}</span>
        <div><small>${row.market} · ${row.industry || "產業未分類"}</small><h3>${row.symbol} ${row.name}</h3></div>
        <strong>${number(row.close)}</strong>
        <dl><div><dt>成交金額</dt><dd>${money(row.turnover)}</dd></div><div><dt>成交量</dt><dd>${lots(row.volume)}</dd></div></dl>
      </article>`).join("");
    $("#popularGrid").querySelectorAll(".popular-card").forEach(card => {
      const open = () => window.location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
      card.addEventListener("click", open); card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    });
  } catch (error) { status.textContent = error.message; toast(error.message, true); }
}

async function refreshPopularStocks() {
  const button = $("#refreshPopularButton"); button.disabled = true; button.textContent = "正在更新全市場行情…";
  try { await api("/sync", { method: "POST" }); await loadPopularStocks(); toast("熱門股票排行已更新"); }
  catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "更新熱門排行"; }
}

async function refreshData() {
  const button = $("#refreshRecommendationButton"); button.disabled = true; button.textContent = "正在更新全市場資料…";
  try { await api("/screener/sync", { method: "POST" }); toast("基本面資料已更新"); await loadRecommendations(); }
  catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "更新資料並重新評分"; }
}
async function checkHealth() {
  const el = $("#apiStatus");
  try { await api("/health"); el.className = "status-dot online"; el.innerHTML = "<i></i>服務正常"; }
  catch { el.className = "status-dot offline"; el.innerHTML = "<i></i>服務中斷"; }
}
$("#refreshRecommendationButton").addEventListener("click", refreshData);
$("#reloadButton").addEventListener("click", loadRecommendations);
$("#recommendationProfile").addEventListener("change", () => { updateMethod(); loadRecommendations(); });
$("#refreshPopularButton").addEventListener("click", refreshPopularStocks);
updateMethod(); checkHealth(); loadPopularStocks(); loadRecommendations();
