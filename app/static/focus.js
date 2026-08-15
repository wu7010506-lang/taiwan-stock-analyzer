const $ = selector => document.querySelector(selector);

const actionLabel = {
  next_open_buy: "確認後才研究",
  wait_breakout: "等待突破",
  no_trade: "暫不操作",
  observation: "模型觀察",
};

function text(value, fallback = "尚無資料") {
  return value == null || value === "" ? fallback : String(value);
}

function card(row) {
  const model = row.source === "vnext_formal_model";
  const state = model ? "observation" : row.action;
  const details = [];
  if (model) {
    details.push(`模型排名第 ${text(row.model_rank)} 名`);
    details.push(text(row.reason, "基本面與估值通過正式研究資格"));
    if (row.technical_signal) {
      details.push({ favorable: "短線時機較佳", wait: "短線尚待確認", avoid: "短線偏不利" }[row.technical_signal] || "短線資料待確認");
    }
  } else {
    details.push(text(row.reason));
    if (row.action === "wait_breakout") details.push("下一步：收盤突破近 20 日高點，且成交量確認後再檢視");
    if (row.action === "no_trade") details.push("下一步：先不操作，等待短線條件改善後再檢視");
    if (row.invalidation_price != null) details.push(`風險界線 ${Number(row.invalidation_price).toLocaleString("zh-TW", { maximumFractionDigits: 1 })}`);
  }
  const date = row.technical_as_of || row.as_of_date || row.latest_price_date || row.signal_date;
  return `<a class="dashboard-action-card ${state === "next_open_buy" ? "buy" : "wait"}" href="/stock/?symbol=${encodeURIComponent(row.symbol)}"><div><strong>${text(row.symbol)} ${text(row.name, "")}</strong><small>${details.join("；")}${date ? `。資料日期：${date}` : ""}</small></div><b>${actionLabel[state] || "觀察"}</b></a>`;
}

async function loadFocus() {
  const response = await fetch("/dashboard");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "無法讀取今日資料");
  const shortTerm = data.short_term?.data || {};
  const market = data.market || {};
  const modelRows = shortTerm.model_observations || [];
  const seen = new Set(modelRows.map(row => row.symbol));
  // vNext candidates remain first when available.  A strict-data day may have
  // none, so always fill the remaining places from the fixed short-term list.
  const rows = [
    ...modelRows.slice(0, 5),
    ...(shortTerm.decisions || []).filter(row => !seen.has(row.symbol)).slice(0, Math.max(0, 10 - modelRows.slice(0, 5).length)),
  ].slice(0, 10);
  const marketText = market.regime ? `市場狀態：${market.regime}` : "市場狀態尚未提供";
  const scoreText = market.market_score == null ? "" : `｜市場分數 ${Number(market.market_score).toFixed(0)}`;
  $("#focusStatus").textContent = `${marketText}${scoreText}。清單資料以各列標示日期為準。`;
  $("#focusList").innerHTML = rows.length ? rows.map(card).join("") : "<p class=\"dashboard-empty\">目前沒有足夠資料產生關注名單；請先查看研究與資料頁的資料品質狀態。</p>";
}

loadFocus().catch(error => {
  $("#focusStatus").textContent = `暫時無法產生清單：${error.message}`;
  $("#focusList").innerHTML = "<p class=\"dashboard-empty\">請稍後重試，或前往研究與資料查看資料狀態。</p>";
});
