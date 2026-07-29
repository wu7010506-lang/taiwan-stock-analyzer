const $ = selector => document.querySelector(selector);
const number = (value, suffix="") => value == null ? "—" : `${Number(value).toLocaleString("zh-TW", {maximumFractionDigits:1})}${suffix}`;
const actions = {buy:"可買入",accumulate:"加碼",hold:"持有",wait:"觀望",reduce:"減碼",sell:"賣出",insufficient_data:"資料不足"};
const actionAliases = {build_small:"小額試單",short_history_build:"小額觀察",observation:"觀察"};
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
  verified_material_negative_event:"出現已確認的重大負面事件"
};
const empty = text => `<p class="dashboard-empty">${text}</p>`;

function actionCard(symbol, name, action, detail, href=`/?symbol=${encodeURIComponent(symbol)}`) {
  const translated = (detail || "").split("；").map(item=>reasonLabels[item] || item).join("；");
  return `<a class="dashboard-action-card ${action || "wait"}" href="${href}"><div><strong>${symbol} ${name || ""}</strong><small>${translated || "請開啟個股分析查看理由"}</small></div><b>${actions[action] || actionAliases[action] || "觀望"}</b></a>`;
}

function watchingDecisionDetail(decision = {}) {
  const reasons = (decision.reasons || []).map(item => reasonLabels[item] || item);
  const risks = (decision.risks || []).map(item => reasonLabels[item] || item);
  const details = [];
  if (reasons.length) details.push(`理由：${reasons.join("、")}`);
  if (risks.length) details.push(`限制：${risks.join("、")}`);
  if (decision.value_score != null) details.push(`企業價值 ${number(decision.value_score)} 分`);
  if (decision.timing_score != null) details.push(`進場時機 ${number(decision.timing_score)} 分`);
  if (decision.new_allocation_percent > 0) details.push(`建議上限 ${number(decision.new_allocation_percent, "%")}`);
  return details.join("；");
}

async function loadDashboard() {
  const response = await fetch("/dashboard");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `讀取失敗（${response.status}）`);
  const market = data.market || {};
  const portfolio = data.portfolio?.data || {};
  const quality = data.quality?.data || {};
  const recommendations = data.recommendations?.data || {};
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
  $("#candidateActions").innerHTML = candidates.length ? candidates.map(row => actionCard(row.symbol,row.name,row.action,`價值 ${number(row.value_score)}｜進場 ${number(row.timing_score)}｜部位 ${number(row.suggested_position_percent,"%")}`)).join("") : empty("目前沒有通過完整資料門檻的正式候選。");
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
      try { context = JSON.parse(row.market_context_json || "{}"); } catch { /* preserve audit row */ }
      return `<article><strong>${row.decision_date}</strong><span>市場：${context.regime || "unknown"} / 分數 ${number(context.market_score)}</span><small>品質快照 #${row.quality_snapshot_id || "—"}；vNext ${row.vnext_snapshot_date || "—"}</small></article>`;
    }).join("");
  } catch { target.textContent = "決策履歷目前無法讀取。"; }
}

$("#reloadDashboard").addEventListener("click",()=>loadDashboard().catch(error=>alert(error.message)));
loadDashboard().catch(error=>{$("#decisionGate").textContent=error.message;});
