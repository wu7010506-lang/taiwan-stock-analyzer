const $ = selector => document.querySelector(selector);

function value(input) { return input == null || input === "" ? "—" : input; }
function statusLabel(status) { return status === "healthy" ? "資料正常" : status === "critical" ? "需要立即處理" : "部分資料需注意"; }

async function loadQuality() {
  const response = await fetch("/data-quality");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `讀取失敗（${response.status}）`);
  const summary = data.summary || {};
  $("#qualitySummary").innerHTML = `
    <article class="quality-state ${data.status}"><span>整體狀態</span><strong>${statusLabel(data.status)}</strong><small>產生時間 ${data.generated_at}</small></article>
    <article><span>嚴重問題</span><strong>${summary.critical || 0}</strong><small>可能影響正式推薦</small></article>
    <article><span>注意事項</span><strong>${summary.warning || 0}</strong><small>同步或覆蓋率未完整</small></article>
    <article><span>最近同步</span><strong>${value(data.latest_daily_sync?.status)}</strong><small>${value(data.latest_daily_sync?.finished_at || data.latest_daily_sync?.started_at)}</small></article>`;

  const labels = {prices:"日價量",revenues:"月營收",valuations:"估值",financials:"財報",institutions:"法人買賣"};
  $("#coverageRows").innerHTML = Object.entries(data.markets || {}).flatMap(([market,datasets]) =>
    Object.entries(datasets).map(([name,row]) => `<tr><td>${market}</td><td>${labels[name] || name}</td><td>${value(row.latest_date)}</td><td>${row.covered_stocks}/${row.total_stocks}</td><td><span class="coverage-pill ${row.coverage_percent < 70 ? "critical" : row.coverage_percent < 95 ? "warning" : "healthy"}">${row.coverage_percent}%</span></td><td>${row.stale_stocks}</td></tr>`)
  ).join("");

  const queues = data.queues || {};
  $("#queueCards").innerHTML = [["五年研究資料",queues.fundamentals],["三年歷史價格",queues.prices]].map(([label,row]) => `<div><span>${label}</span><strong>${row?.completion_percent || 0}%</strong><small>完成 ${row?.completed || 0}/${row?.total || 0}｜失敗 ${row?.failed || 0}</small></div>`).join("");
  $("#qualityIssues").innerHTML = data.issues?.length ? data.issues.map(issue => `<article class="quality-issue ${issue.severity}"><strong>${issue.title}</strong><p>${issue.detail || "沒有更多錯誤資訊"}</p><small>建議：${issue.action}</small></article>`).join("") : '<div class="empty-state"><h2>目前沒有資料品質警告</h2><p>仍應在交易前確認資料日期與官方來源。</p></div>';
  $("#sourceRows").innerHTML = (data.sources || []).map(row => `<tr><td>${row.label}</td><td>${row.primary}</td><td>${row.fallback}</td><td>${row.formal_use}</td></tr>`).join("");
}

$("#reloadQualityButton").addEventListener("click", () => loadQuality().catch(error => alert(error.message)));
loadQuality().catch(error => { $("#qualitySummary").textContent = error.message; });
