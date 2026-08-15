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
    Object.entries(datasets).map(([name,row]) => {
      const exact = ["prices", "institutions"].includes(name) && row.exact_date_coverage_percent != null;
      const covered = exact ? row.exact_date_stocks : row.covered_stocks;
      const coverage = exact ? row.exact_date_coverage_percent : row.coverage_percent;
      const stale = exact ? row.off_latest_date_stocks : row.stale_stocks;
      return `<tr><td>${market}</td><td>${labels[name] || name}${exact ? "（同日）" : ""}</td><td>${value(row.latest_date)}</td><td>${covered}/${row.total_stocks}</td><td><span class="coverage-pill ${coverage < 70 ? "critical" : coverage < 95 ? "warning" : "healthy"}">${coverage}%</span></td><td>${stale}</td></tr>`;
    })
  ).join("");

  const quarantine = data.quarantine || {};
  $("#quarantineSummary").textContent = quarantine.active
    ? `目前有 ${quarantine.total_symbols || 0} 檔價格未對齊各市場最新交易日，已禁止進入當日排行榜。`
    : "所有股票價格均已對齊各市場最新交易日，沒有隔離項目。";
  $("#quarantineRows").innerHTML = (quarantine.groups || []).map(group => {
    const samples = (group.samples || []).map(row =>
      `<a href="/stock/?symbol=${encodeURIComponent(row.symbol)}">${row.symbol} ${row.name || ""}</a>${row.latest_date ? `（${row.latest_date}）` : "（無資料）"}`
    ).join("、");
    return `<tr><td>${group.market}</td><td>${value(group.target_date)}</td><td>${group.lagging_count}</td><td>${samples || "—"}${group.lagging_count > (group.samples || []).length ? "…" : ""}</td></tr>`;
  }).join("") || '<tr><td colspan="4">沒有被隔離的股票</td></tr>';

  const queues = data.queues || {};
  const vnextCoverage = data.vnext_history_coverage || {};
  const fundamentalLabel = queues.fundamentals?.full_market_initialized ? "全市場五年研究資料" : "五年研究資料（尚未建立全市場佇列）";
  const queueCards = [[fundamentalLabel,queues.fundamentals],["三年歷史價格",queues.prices]].map(([label,row]) => `<div><span>${label}</span><strong>${row?.completion_percent || 0}%</strong><small>完成 ${row?.completed || 0}/${row?.total || 0}｜剩餘 ${row?.remaining ?? ((row?.total || 0)-(row?.completed || 0))}｜失敗 ${row?.failed || 0}${row?.quota_limited ? `｜額度暫停 ${row.quota_limited}` : ""}</small></div>`);
  queueCards.push(`<div><span>vNext 歷史資格</span><strong>${vnextCoverage.eligible_percent || 0}%</strong><small>合格 ${vnextCoverage.eligible || 0}/${vnextCoverage.checked || 0}｜財報缺口 ${vnextCoverage.missing_counts?.financial_history || 0}｜價格缺口 ${vnextCoverage.missing_counts?.price_history || 0}｜新鮮度缺口 ${vnextCoverage.missing_counts?.freshness || 0}</small></div>`);
  $("#queueCards").innerHTML = queueCards.join("");
  const resolved = (data.resolved_since_sync || []).map(message => `<article class="quality-issue resolved"><strong>已修復</strong><p>${message}</p><small>下一次全站同步會建立新的完整紀錄。</small></article>`).join("");
  $("#qualityIssues").innerHTML = (data.issues?.length ? data.issues.map(issue => `<article class="quality-issue ${issue.severity}"><strong>${issue.title}</strong><p>${issue.detail || "沒有更多錯誤資訊"}</p><small>建議：${issue.action}</small></article>`).join("") : '<div class="empty-state"><h2>目前沒有資料品質警告</h2><p>仍應在交易前確認資料日期與官方來源。</p></div>') + resolved;
  $("#sourceRows").innerHTML = (data.sources || []).map(row => `<tr><td>${row.label}</td><td>${row.primary}</td><td>${row.fallback}</td><td>${row.formal_use}</td></tr>`).join("");
  const contracts = data.contracts || {};
  $("#contractRows").innerHTML = (contracts.checks || []).map(row => `<tr><td>${row.label}</td><td>${row.required_coverage_percent}%</td><td>${row.actual_coverage_percent}%</td><td>${value(row.latest_date)}</td><td><span class="coverage-pill ${row.status === "passed" ? "healthy" : "critical"}">${row.status === "passed" ? "通過" : row.reason}</span></td></tr>`).join("") || '<tr><td colspan="5">尚無資料契約結果</td></tr>';
}

$("#reloadQualityButton").addEventListener("click", () => loadQuality().catch(error => alert(error.message)));
$("#snapshotQualityButton").addEventListener("click", async () => {
  const message = $("#snapshotMessage");
  try {
    const response = await fetch("/data-quality/snapshot", {method:"POST"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `保存失敗（${response.status}）`);
    message.textContent = `已保存品質快照 #${result.snapshot_id}；資料契約：${result.contracts?.status === "passed" ? "通過" : "未通過"}`;
  } catch (error) { message.textContent = error.message; }
});
$("#syncAllFinancialsButton").addEventListener("click", async () => {
  const button = $("#syncAllFinancialsButton");
  const message = $("#financialBatchMessage");
  button.disabled = true;
  button.textContent = "正在補齊下一批…";
  message.textContent = "每批最多處理 10 檔；進度會保存，每日收盤同步也會自動接續。";
  try {
    const response = await fetch("/financials/history/batch?scope=all&batch_size=10&years=5&retry_failed=true", {method:"POST"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `同步失敗（${response.status}）`);
    const progress = result.progress || {};
    message.textContent = result.quota_paused
      ? `API 額度已用完，本次已安全暫停；完成 ${progress.completed}/${progress.total}，稍後或下次收盤同步會繼續。`
      : `本批完成，累計 ${progress.completed}/${progress.total}，剩餘 ${progress.remaining || 0} 檔。`;
    await loadQuality();
  } catch (error) { message.textContent = error.message; }
  finally { button.disabled = false; button.textContent = "補齊下一批完整財報"; }
});
loadQuality().catch(error => { $("#qualitySummary").textContent = error.message; });
