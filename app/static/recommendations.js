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

const vnextLabels = {
  buy:"可買入", accumulate:"分批加碼", hold:"持有", wait:"觀望", reduce:"減碼", sell:"賣出",
  insufficient_data:"資料不足", observation:"觀察名單",
  high:"高", medium:"中", low:"低", unknown:"未知",
  durable_business_quality:"企業品質具持續性",
  cashflow_supports_earnings:"現金流能支持獲利",
  valuation_has_margin_of_safety:"估值具有安全邊際",
  short_history_model:"上市歷史較短，使用觀察模型",
  recent_financials_available:"近期財報可使用",
  fundamentals_deteriorate:"基本面惡化",
  valuation_overheats:"估值進入過熱區",
  market_regime_changes:"市場狀態改變",
  market_risk_off:"市場進入避險狀態",
  market_overheat:"整體市場偏熱",
  market_extreme_overheat:"整體市場極度過熱",
  institution_driven_surge:"近期漲勢可能由法人集中買盤推動",
  verified_material_negative_event:"出現已確認的重大負面事件",
  limited_valuation_history:"估值歷史樣本較短",
};
function vnextLabel(value) {
  if (value == null || value === "") return "—";
  return vnextLabels[value] || String(value).replaceAll("_", " ");
}
function vnextList(values) { return (values || []).map(vnextLabel); }

const profiles = {
  vnext: { title: "新版研究型推薦 vNext", weights: "企業品質70｜估值30｜進場時機獨立判斷｜市場現金與集中度限制", rule: "五年完整財報、現金流、三年價格與資料新鮮度符合時才給正式建議。" },
  balanced: { title: "綜合多因子", weights: "品質25｜估值20｜技術15｜營收15｜籌碼8｜流動性7｜大盤7｜時事3", rule: "營收分數由最新月營收年增與年度累計營收年增各占一半合成。" },
  long_term_quality: { title: "長期優質企業", weights: "品質30｜規模韌性20｜持續性15｜估值15｜流動性7｜營收5｜大盤3｜技術3｜籌碼1｜時事1", rule: "長期核心占80%；財報少於3期時，獲利持續性維持中性並顯示資料覆蓋率。" },
  evidence_based: { title: "研究型推薦（新版）", weights: "企業品質30｜現金流20｜持續性15｜估值15｜風險韌性10｜成長品質5｜市場配適5", rule: "至少五年且12期現金流才納入。成長若缺乏自由現金流支持會被封頂；市場偏空時提高品質、現金流與風險門檻。" },
  value: { title: "價值型", weights: "估值30｜品質25｜技術15｜年營收10｜月營收5｜其餘15", rule: "硬性條件：EPS 為正、PE＜15、PB＜2、負債比不高於 70%。" },
  growth: { title: "成長型", weights: "品質20｜月營收20｜技術20｜年營收10｜估值10｜其餘20", rule: "硬性條件：EPS 為正、月營收年增至少 20%、ROE 為正。" },
  quality: { title: "品質型", weights: "品質35｜估值20｜技術15｜年營收10｜月營收7｜其餘13", rule: "硬性條件：EPS 為正、ROE 至少 10%、毛利率為正、負債比不高於 60%。" },
};

function factorCards(row) {
  if (row.profile === "vnext") return `<span>企業品質<strong>${number(row.company_quality?.score)}</strong></span><span>資本報酬<strong>${number(row.company_quality?.capital_returns)}</strong></span><span>現金流品質<strong>${number(row.company_quality?.cashflow_quality)}</strong></span><span>估值<strong>${number(row.valuation_score)}</strong></span><span>進場時機<strong>${number(row.timing_score)}</strong></span><span>籌碼擁擠<strong>${vnextLabel(row.crowding_risk)}</strong></span><span>建議部位<strong>${number(row.suggested_position_percent)}%</strong></span>`;
  if (row.profile === "evidence_based") return `<span>企業品質<strong>${number(row.business_quality_score)}</strong></span><span>現金流<strong>${number(row.cashflow_quality_score)}</strong><small>FCF 正值 ${row.positive_fcf_ratio == null ? "—" : growth(row.positive_fcf_ratio * 100)}</small></span><span>持續性<strong>${number(row.durability_score)}</strong><small>${row.evidence_years} 年｜現金流 ${row.cash_flow_periods} 期</small></span><span>估值<strong>${number(row.value_score)}</strong><small>自身歷史 ${row.historical_value_score == null ? "—" : number(row.historical_value_score)}｜${row.historical_valuation_observations || 0} 日</small></span><span>風險韌性<strong>${number(row.risk_resilience_score)}</strong></span><span>成長品質<strong>${number(row.growth_quality_score)}</strong><small>年複合 ${row.revenue_cagr_annual == null ? "—" : growth(row.revenue_cagr_annual)}</small></span><span>市場配適<strong>${number(row.market_score)}</strong></span>`;
  if (row.profile === "long_term_quality") return `<span>品質<strong>${number(row.quality_score)}</strong></span><span>持續性<strong>${number(row.durability_score)}</strong><small>覆蓋 ${row.durability_coverage}%｜${row.financial_history_periods} 期</small></span><span>估值<strong>${number(row.value_score)}</strong></span><span>規模韌性<strong>${number(row.scale_score)}</strong></span><span>營收<strong>${number(row.revenue_growth_score)}</strong></span><span>技術<strong>${number(row.technical_score)}</strong></span><span>流動性<strong>${number(row.liquidity_score)}</strong></span><span>大盤<strong>${number(row.market_score)}</strong></span>`;
  return `<span>品質<strong>${number(row.quality_score)}</strong></span><span>估值<strong>${number(row.value_score)}</strong></span><span>技術<strong>${number(row.technical_score)}</strong></span><span>營收<strong>${number(row.revenue_growth_score)}</strong><small>月 ${growth(row.revenue_yoy)}｜累計 ${row.annual_revenue_yoy == null ? "—" : growth(row.annual_revenue_yoy)}</small></span><span>籌碼<strong>${number(row.chip_score)}</strong></span><span>流動性<strong>${number(row.liquidity_score)}</strong></span><span>大盤<strong>${number(row.market_score)}</strong></span><span>時事<strong>${number(row.news_score)}</strong></span>`;
}

async function loadMarketContext(refresh = false) {
  const el = $("#marketContext");
  try {
    const data = await api(`/market-context${refresh ? "?refresh=true" : ""}`);
    el.innerHTML = `<div class="market-regime-status" data-regime="${data.regime || ""}"><small>市場狀態</small><strong>${data.regime}</strong></div>
      <div><small>大盤分數</small><strong>${number(data.market_score)}</strong></div>
      <div><small>近 5 日</small><strong>${growth(data.index_change_5d)}</strong></div>
      <div><small>近 20 日</small><strong>${growth(data.index_change_20d)}</strong></div>
      <div><small>市場過熱</small><strong>${number(data.overheat_score)}</strong></div>
      <div><small>20日乖離</small><strong>${growth(data.distance_ma20_percent)}</strong></div>
      <div><small>大盤 RSI</small><strong>${number(data.index_rsi_14)}</strong></div>
      <div><small>資料日期</small><strong>${data.as_of || "—"}</strong></div>`;
    if (!data.available) toast("官方市場資料暫時不可用，評分維持中性", true);
  } catch (error) { el.textContent = error.message; }
}

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
    const response = profile === "vnext"
      ? await api("/recommendations/vnext?limit=24")
      : await api(`/recommendations?limit=24&min_completeness=70&profile=${profile}`);
    const rows = profile === "vnext"
      ? response.recommendations.map(row => ({
          ...row, profile: "vnext", score: row.value_score, rating: row.action,
          reasons: row.supporting_reasons || [], risks: row.risks || [],
          institution_influence: row.crowding_risk || "unknown",
          speculation_risk: row.crowding_risk || "unknown",
          institution_influence_reasons: [], industry_adjustments: [],
          invalidation_conditions: row.change_conditions || [],
        }))
      : response;
    const gate = profile === "vnext" ? response.formal_recommendation_gate : null;
    status.textContent = gate && !gate.allowed
      ? `vNext 清單僅供研究觀察：${gate.message}`
      : rows.length ? `顯示 ${rows.length} 檔多因子研究候選｜市場：${rows[0].market_regime || "中性"}` : "沒有足夠完整的資料";
    $("#recommendationEmpty").classList.toggle("hidden", rows.length > 0);
    const grid = $("#recommendationGrid"); grid.hidden = rows.length === 0;
    grid.innerHTML = rows.map((row, index) => `
      <article class="recommendation-card" data-symbol="${row.symbol}" tabindex="0" role="link">
        <div class="recommendation-rank">#${index + 1}</div>
        <div class="recommendation-head"><div><span>${row.profile === "vnext" ? vnextLabel(row.rating) : (row.evidence_decision || row.rating)}</span><h2>${row.symbol} ${row.name}</h2><small>${row.market} · ${row.profile === "vnext" ? (row.industry_model || row.industry || "產業未分類") : (row.industry || "產業未分類")}${row.profile === "evidence_based" ? ` · ${row.industry_model}` : ""}</small></div><strong>${number(row.score)}<i>分</i></strong></div>
        <div class="score-bar"><i style="width:${Math.min(row.score, 100)}%"></i></div>
        <div class="factor-grid">${factorCards(row)}</div>
        <div class="institution-risk ${["高","high"].includes(row.speculation_risk) ? "high" : ["中","medium"].includes(row.speculation_risk) ? "medium" : "low"}"><strong>法人推動 ${row.profile === "vnext" ? vnextLabel(row.institution_influence) : row.institution_influence}</strong><span>炒作風險 ${row.profile === "vnext" ? vnextLabel(row.speculation_risk) : (row.speculation_risk || "—")}</span><small>${row.institution_influence_reasons.length ? row.institution_influence_reasons.join("｜") : "未見短線急漲與法人集中買超同時出現"}</small></div>
        <ul class="reason-list">${[...(row.industry_adjustments || []), ...(row.profile === "vnext" ? vnextList(row.reasons) : row.reasons)].slice(0, 5).map(reason => `<li>${reason}</li>`).join("")}</ul>
        ${(row.invalidation_conditions?.length || row.risks.length) ? `<div class="risk-note">風險／失效條件：${(row.profile === "vnext" ? vnextList([...(row.invalidation_conditions || []), ...row.risks]) : [...(row.invalidation_conditions || []), ...row.risks]).slice(0, 5).join("、")}</div>` : ""}
        <div class="recommendation-footer"><span>PE ${number(row.pe)} · ROE ${growth(row.roe)} · 營收 ${growth(row.revenue_yoy)}</span><button class="quick-watch" data-symbol="${row.symbol}" type="button">＋ 我的股票</button></div>
      </article>`).join("");
    grid.querySelectorAll(".recommendation-card").forEach(card => {
      const open = () => window.location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
      card.addEventListener("click", open); card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    });
    grid.querySelectorAll(".quick-watch").forEach(button => button.addEventListener("click", event => addWatch(event, button.dataset.symbol)));
  } catch (error) { status.textContent = error.message; toast(error.message, true); }
}

async function loadResearchSyncStatus() {
  const data = await api("/financials/history/batch/status?target_limit=100");
  const status = $("#researchSyncStatus");
  status.textContent = data.total ? `研究資料：完成 ${data.completed}/${data.total}（${data.completion_percent}%）｜待處理 ${data.pending}｜失敗 ${data.failed}` : "研究資料尚未建立批次同步清單";
  return data;
}

async function syncResearchData() {
  const button = $("#syncResearchButton"); button.disabled = true;
  try {
    const previous = await loadResearchSyncStatus();
    let retryFailed = previous.pending === 0 && previous.failed > 0;
    let progress;
    do {
      button.textContent = "正在補齊研究資料…";
      const result = await api(`/financials/history/batch?target_limit=100&batch_size=10&years=5&retry_failed=${retryFailed}`, { method: "POST" });
      retryFailed = false;
      progress = result.progress;
      await loadResearchSyncStatus();
    } while (progress.pending > 0);
    toast(progress.failed ? `已完成 ${progress.completed} 檔；${progress.failed} 檔受 API 額度限制，可稍後按此按鈕重試` : `研究資料同步完成 ${progress.completed} 檔`);
    await loadRecommendations();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "補齊前 100 檔研究資料"; }
}

async function loadPriceSyncStatus() {
  const data = await api("/prices/history/batch/status?target_limit=100");
  $("#priceSyncStatus").textContent = data.total ? `歷史價格：完成 ${data.completed}/${data.total}（${data.completion_percent}%）｜待處理 ${data.pending}｜失敗 ${data.failed}` : "歷史價格尚未建立同步清單";
  return data;
}

async function syncPriceHistory() {
  const button = $("#syncPriceHistoryButton"); button.disabled = true;
  try {
    const previous = await loadPriceSyncStatus();
    let retryFailed = previous.pending === 0 && previous.failed > 0;
    let progress;
    do {
      button.textContent = "正在補齊歷史價格…";
      const result = await api(`/prices/history/batch?target_limit=100&batch_size=10&years=3&retry_failed=${retryFailed}`, { method: "POST" });
      retryFailed = false; progress = result.progress;
      await loadPriceSyncStatus();
    } while (progress.pending > 0);
    toast(progress.failed ? `歷史價格完成 ${progress.completed} 檔；失敗 ${progress.failed} 檔，可稍後重試` : "歷史價格同步完成");
    await loadRecommendations();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "補齊前 100 檔歷史價格"; }
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
$("#syncResearchButton").addEventListener("click", syncResearchData);
$("#syncPriceHistoryButton").addEventListener("click", syncPriceHistory);
$("#refreshContextButton").addEventListener("click", async event => { event.currentTarget.disabled = true; await loadMarketContext(true); await loadRecommendations(); event.currentTarget.disabled = false; });
updateMethod(); checkHealth(); loadMarketContext(); loadPopularStocks(); loadResearchSyncStatus(); loadPriceSyncStatus(); loadRecommendations();
