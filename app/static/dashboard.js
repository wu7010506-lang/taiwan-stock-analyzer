const $ = selector => document.querySelector(selector);
const number = (value, suffix="") => value == null ? "—" : `${Number(value).toLocaleString("zh-TW", {maximumFractionDigits:1})}${suffix}`;
const actions = {buy:"可買入",accumulate:"加碼",hold:"持有",wait:"觀望",reduce:"減碼",sell:"賣出",exit_next_open:"明日出場",reduce_next_open:"明日減碼",insufficient_data:"資料不足"};
const shortTermActions = {next_open_buy:"明日可買",wait_breakout:"等待突破",no_trade:"不交易",observation:"模型觀察"};
const actionAliases = {build_small:"小額分批",short_history_build:"資料不足，不進場",short_history_watch:"持續追蹤",observation:"持續追蹤"};
const reasonLabels = {
  single_stock_limit_exceeded:"單一持股比重過高", durable_business_quality:"企業品質穩定",
  cashflow_supports_earnings:"現金流支持獲利", valuation_has_margin_of_safety:"估值具安全邊際",
  short_history_model:"上市歷史較短，採觀察模型", recent_financials_available:"近期財報可用",
  insufficient_vnext_data:"研究資料尚未達正式門檻",
  risk_off_quality_candidate:"偏空市場中仍達品質門檻，允許小額分批",
  limited_operating_history:"價格歷史不足，尚不能列為正式長期推薦",
  market_risk_off:"整體市場處於避險狀態",
  market_overheat:"整體市場偏熱，不建議追價",
  market_extreme_overheat:"整體市場極度過熱",
  institution_driven_surge:"法人集中買盤與急漲同時出現",
  limited_valuation_history:"估值歷史樣本較短",
  verified_material_negative_event:"出現已確認的重大負面事件",
  technical_timing_not_favorable:"技術時機尚未確認",
  technical_history_under_60_sessions:"技術歷史不足 60 個交易日",
  technical_trend_not_confirmed:"未站穩 20／60 日均線趨勢",
  relative_strength_unavailable:"大盤相對強弱資料不足",
  relative_strength_negative:"近 20 日相對大盤偏弱",
  technical_overextended:"股價偏離 20 日線過大，避免追價",
  breakout_without_volume_confirmation:"突破尚無量能確認",
  long_upper_shadow:"出現長上影線，留意賣壓",
  bearish_engulfing:"出現空頭吞沒型態",
  trend_strength_unavailable:"ADX 趨勢強度資料不足",
  trend_strength_weak:"ADX 顯示趨勢強度不足",
  money_flow_overheated:"MFI 資金流偏熱",
  volatility_high:"NATR 波動偏高，應縮小部位",
  volatility_extreme:"NATR 波動極高，僅能極小部位"
  ,short_term_stop_loss:"已跌破短線停損價"
  ,short_term_target_reached:"已達短線目標價"
  ,short_term_time_exit:"已達最長 10 個交易日持有期限"
  ,short_term_rule_intact:"短線停損、目標與持有期限尚未觸發"
};
const empty = text => `<p class="dashboard-empty">${text}</p>`;

function actionCard(symbol, name, action, detail, href=`/?symbol=${encodeURIComponent(symbol)}`) {
  const translated = (detail || "").split("；").map(item=>reasonLabels[item] || item).join("；");
  return `<a class="dashboard-action-card ${action || "wait"}" href="${href}"><div><strong>${symbol} ${name || ""}</strong><small>${translated || "請開啟個股分析查看理由"}</small></div><b>${actions[action] || actionAliases[action] || "觀望"}</b></a>`;
}

function firstLabel(items = []) {
  return items.map(item => reasonLabels[item] || item).find(Boolean);
}

function watchingDecisionDetail(decision = {}) {
  const reasons = (decision.reasons || []).map(item => reasonLabels[item] || item);
  const risks = (decision.risks || []).map(item => reasonLabels[item] || item);
  const technical = decision.technical_timing || {};
  if (decision.action === "insufficient_data") {
    return `今天不進場：${firstLabel(risks) || "研究資料未達正式門檻"}。`;
  }
  if (decision.action === "wait" || decision.action === "observation") {
    return `今天先不買：${firstLabel(risks) || "尚未出現足夠進場條件"}。`;
  }
  if (decision.new_allocation_percent > 0) {
    const reason = firstLabel(reasons) || "企業品質與估值條件通過";
    const timing = technical.signal === "favorable"
      ? "系統已確認價格與風險條件"
      : "仍須等待系統確認進場條件";
    return `可分批建立，新增部位最多 ${number(decision.new_allocation_percent, "%")}：${reason}；${timing}。`;
  }
  return `今天不新增部位：${firstLabel(risks) || firstLabel(reasons) || "條件尚未完整"}。`;
}

function candidateDecisionDetail(row = {}) {
  const technical = row.technical_timing || {};
  const details = [`價值 ${number(row.value_score)}`, `進場 ${number(row.timing_score)}`,
    `部位 ${number(row.suggested_position_percent, "%")}`];
  if (technical.status === "available") {
    const labels = {favorable:"技術時機可評估",wait:"技術面等待",avoid:"技術面暫避"};
    details.push(`${labels[technical.signal] || "技術未定"} ${number(technical.score)} 分`);
  } else details.push("技術資料不足");
  if (row.technical_timing_constrained) details.push("原模型可選，但今日等待技術確認");
  return details.join("；");
}

function shortTermCard(row = {}) {
  const detail = [];
  if (row.source === "vnext_formal_model") {
    detail.push(`正式模型第 ${row.model_rank} 名`);
    if (row.as_of_date) detail.push(`模型資料截至 ${row.as_of_date}`);
    if (row.technical_as_of) detail.push(`技術資料截至 ${row.technical_as_of}`);
    if (row.technical_signal) {
      const timing = {favorable:"技術時機偏有利",wait:"技術時機未確認",avoid:"技術時機應避開"};
      detail.push(timing[row.technical_signal] || "技術時機資料不足");
    }
    detail.push(row.reason);
  } else {
    detail.push(row.reason, `持有 ${row.holding_sessions || "3–10"} 個交易日`);
  }
  if (row.invalidation_price != null) detail.push(`失效價 ${number(row.invalidation_price)}`);
  if (row.action === "next_open_buy") detail.push(`新增部位上限 ${number(row.max_new_position_percent, "%")}`);
  return `<a class="dashboard-action-card ${row.action === "next_open_buy" ? "buy" : "wait"}" href="/?symbol=${encodeURIComponent(row.symbol)}"><div><strong>${row.symbol} ${row.name || ""}</strong><small>${detail.join("；")}</small></div><b>${shortTermActions[row.action] || "不交易"}</b></a>`;
}

async function loadDashboard() {
  const response = await fetch("/dashboard");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `讀取失敗（${response.status}）`);
  const market = data.market || {};
  const portfolio = data.portfolio?.data || {};
  const quality = data.quality?.data || {};
  const recommendations = data.recommendations?.data || {};
  const shortTerm = data.short_term?.data || {};
  const gate = data.decision_gate || {};
  $("#decisionGate").className = `decision-gate ${gate.status}`;
  $("#decisionGate").innerHTML = `<strong>${gate.status === "open" ? "資料檢查通過" : "交易前需要核對"}</strong><span>${gate.message}</span>`;
  $("#dashboardSummary").innerHTML = [
    ["市場狀態",market.regime || "未知"],["大盤分數",number(market.market_score)],["建議現金",number(portfolio.market_strategy?.cash_target_percent ?? recommendations.cash_target_percent,"%")],["資料警告",number(quality.summary?.issues || 0)],["持有股票",number(portfolio.held_count || 0)],["觀察股票",number(portfolio.watching_count || 0)]
  ].map(([label,value])=>`<article><span>${label}</span><strong>${value}</strong></article>`).join("");
  const held = portfolio.positions || [];
  $("#heldActions").innerHTML = held.length ? held.map(row => actionCard(row.symbol,row.name,row.portfolio_decision?.action,(row.portfolio_decision?.reasons || []).slice(0,2).join("；"))).join("") : empty("尚未輸入持有部位。");
  const actionPriority = {buy:0,accumulate:0,build_small:1,short_history_build:2,hold:3,wait:4,observation:4,insufficient_data:5};
  const watching = [...(portfolio.watching_decisions || [])].sort((a,b)=>(actionPriority[a.decision?.action] ?? 9)-(actionPriority[b.decision?.action] ?? 9));
  $("#watchActions").innerHTML = watching.length ? watching.map(row => actionCard(row.symbol,row.name,row.decision?.action,watchingDecisionDetail(row.decision))).join("") : empty("尚未加入觀察股票。");
  const candidates = recommendations.recommendations || [];
  $("#candidateActions").innerHTML = candidates.length ? candidates.map(row => actionCard(row.symbol,row.name,row.action,candidateDecisionDetail(row))).join("") : empty("目前沒有通過完整資料門檻的正式候選。");
  const modelObservations = shortTerm.model_observations || [];
  const observedSymbols = new Set(modelObservations.map(row => row.symbol));
  // Keep this actionable: five highest-integrity model observations plus up
  // to five liquid, fundamental-safety candidates.  The latter arrive already
  // ordered by the fixed short-term engine (setup state, then liquidity).
  const shortTermRows = [
    ...modelObservations.slice(0, 5),
    ...(shortTerm.decisions || []).filter(row => !observedSymbols.has(row.symbol)).slice(0, 5),
  ].slice(0, 10);
  $("#shortTermActions").innerHTML = shortTermRows.length ? shortTermRows.map(shortTermCard).join("") : empty("沒有通過短線基本面門檻的候選；這不是可用預設分數取代的情況。");
  const risks = [...(portfolio.warnings || []),...(quality.issues || []).slice(0,5).map(row=>row.title)];
  $("#riskActions").innerHTML = risks.length ? `<ul class="dashboard-risk-list">${risks.map(row=>`<li>${row}</li>`).join("")}</ul>` : empty("目前沒有高優先風險警告。");
  loadDecisionHistory();
}

async function loadDecisionHistory() {
  const target = $("#decisionHistory");
  try {
    const response = await fetch("/dashboard/history?limit=14");
    const logs = await response.json();
    if (!response.ok) throw new Error("history unavailable");
    if (!logs.length) { target.textContent = "尚無已保存的每日決策快照。"; return; }
    target.innerHTML = logs.map(row => {
      let context = {};
      let payload = {};
      try { context = JSON.parse(row.market_context_json || "{}"); } catch { /* preserve audit row */ }
      try { payload = JSON.parse(row.payload_json || "{}"); } catch { /* preserve audit row */ }
      const candidates = payload.recommendations?.data?.recommendations || [];
      const gate = payload.decision_gate || {};
      const names = candidates.slice(0, 3).map(item => `${item.symbol} ${item.name || ""}`).join("、");
      return `<article><strong>${row.decision_date}</strong><span>市場：${context.regime || "unknown"} / 分數 ${number(context.market_score)}</span><small>品質快照 #${row.quality_snapshot_id || "—"}；vNext ${row.vnext_snapshot_date || "—"}；決策 ${gate.status || "unknown"}</small>${names ? `<small>當日候選：${names}${candidates.length > 3 ? "…" : ""}</small>` : ""}</article>`;
    }).join("");
  } catch { target.textContent = "決策履歷目前無法讀取。"; }
}

$("#reloadDashboard").addEventListener("click",()=>loadDashboard().catch(error=>alert(error.message)));
loadDashboard().catch(error=>{$("#decisionGate").textContent=error.message;});
