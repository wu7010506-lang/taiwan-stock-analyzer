(() => {
  const $ = selector => document.querySelector(selector);
  const value = (item, suffix = "") => item == null ? "資料不足" : `${Number(item).toLocaleString("zh-TW", {maximumFractionDigits: 2})}${suffix}`;
  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `請求失敗 (${response.status})`);
    return body;
  }
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  function clearRankingBacktestRows(message) {
    $("#rankingBacktestRows").innerHTML = `<tr><td colspan="9">${message}</td></tr>`;
    $("#rankingOperationRows").innerHTML = `<tr><td colspan="4">${message}</td></tr>`;
  }
  async function pollRankingBacktestJob(initialJob) {
    let job = initialJob;
    const startedAt = Date.now();
    while (job.status === "running") {
      const elapsed = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      $("#rankingBacktestSummary").textContent = `背景回測執行中（${elapsed} 秒）；可以留在本頁，網站其他功能仍可使用。`;
      await delay(1500);
      job = await api(`/research/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status === "failed") throw new Error(job.error || "背景回測失敗");
    if (job.status !== "completed" || !job.result) {
      throw new Error("背景回測沒有產生可用結果");
    }
    return job.result;
  }
  function renderHistory(items) {
    $("#experimentRows").innerHTML = items.length ? items.map(item => {
      const result = item.result || {};
      const oos = result.out_of_sample || {};
      const matched = result.out_of_sample_allocation_matched_benchmark || {};
      const oosSize = oos.periods ?? oos.trades;
      const evidence = matched.excess_return_percent == null ? (oos.benchmark_status || "資料不足") : value(matched.excess_return_percent, "%");
      return `<tr><td>${item.created_at || ""}</td><td>${item.strategy_key}<br><small>${item.strategy_version}</small></td><td>${item.status}</td><td>${value(oosSize)}</td><td>${item.lookahead_audit?.status || "資料不足"}</td><td>${evidence}</td></tr>`;
    }).join("") : '<tr><td colspan="6">尚無保存實驗。</td></tr>';
  }
  function renderRankingBacktest(data) {
    const verdicts = {
      insufficient_data: "樣本不足",
      promising_not_yet_validated: "歷史結果具潛力，仍待前瞻驗證",
      mixed_evidence: "證據不一致",
      historical_evidence_does_not_support_ranking: "歷史證據不支持排行榜",
      rejected_lookahead: "PIT 稽核失敗，結果拒絕",
    };
    const assessment = data.effectiveness_assessment || {};
    const details = new Map((assessment.details || []).map(row => [String(row.horizon_sessions), row]));
    $("#rankingBacktestRows").innerHTML = Object.entries(data.horizons || {}).map(([horizon, row]) => {
      const detail = details.get(horizon) || {};
      return `<tr><td>${horizon} 日</td><td>${value(row.matured_items)}／${value(row.unique_signal_dates)} 個訊號日</td><td>${value(row.average_return_percent, "%")}</td><td>${value(row.average_market_excess_return_percent, "%")}</td><td>${value(row.average_industry_excess_return_percent, "%")}</td><td>${value(row.positive_market_excess_rate_percent, "%")}</td><td>${value(detail.top_1_3_minus_rank_4_plus_market_excess_percent, "%")}</td><td>${value(row.average_executable_net_return_percent, "%")}</td><td>${value(row.average_executable_market_excess_percent, "%")}</td></tr>`;
    }).join("") || '<tr><td colspan="9">沒有可評估結果</td></tr>';
    const operationLabels = {
      ready: "ready｜條件完成",
      ready_with_risk: "ready_with_risk｜條件完成但有風險",
      waiting_trigger: "waiting_trigger｜等待觸發",
      reject_rr: "reject_rr｜RR不足",
      blocked_overextended: "blocked_overextended｜過度延伸",
      blocked: "blocked｜其他阻擋",
    };
    const operationOrder = ["ready", "ready_with_risk", "waiting_trigger", "reject_rr", "blocked_overextended", "blocked"];
    const operationBreakdown = data.operation_status_breakdown || {};
    $("#rankingOperationRows").innerHTML = operationOrder.filter(status => operationBreakdown[status]).map(status => {
      const rows = operationBreakdown[status];
      const cell = horizon => {
        const row = rows[String(horizon)] || {};
        return `${value(row.average_executable_net_return_percent, "%")}／${value(row.executable_items)} 筆`;
      };
      return `<tr><td>${operationLabels[status] || status}</td><td>${cell(3)}</td><td>${cell(5)}</td><td>${cell(10)}</td></tr>`;
    }).join("") || '<tr><td colspan="4">沒有可拆分的操作狀態</td></tr>';
    const skipped = data.skipped_signal_dates || [];
    const gapCounts = skipped.reduce((result, row) => {
      result[row.reason] = (result[row.reason] || 0) + 1; return result;
    }, {});
    const gaps = Object.entries(gapCounts).map(([reason, count]) => `${reason}: ${count}`).join("；") || "無";
    const costs = data.methodology?.transaction_costs_bps || {};
    $("#rankingBacktestSummary").innerHTML = `<p><strong>初步判定：${verdicts[assessment.verdict] || assessment.verdict || "未知"}</strong></p><p>有效日期 ${value(data.accepted_runs)}；排名樣本 ${value(data.total_ranked_items)}；PIT 稽核 ${data.lookahead_audit?.status || "未知"}。</p><p>執行代理：隔日開盤進場、持有期末收盤出場；手續費 ${value(costs.commission_each_side)} bps／邊、賣出稅 ${value(costs.sell_tax)} bps、滑價 ${value(costs.slippage_each_side)} bps／邊。</p><p>被排除日期：${gaps}</p><p class="unit-note">${(data.limitations || []).join(" ")}</p>`;
  }
  function renderStudy(data) {
    $("#parameterRows").innerHTML = (data.results || []).map(row => {
      const oos = row.out_of_sample_excess_return_percent == null ? (row.out_of_sample_benchmark_status || "資料不足") : `樣本外 ${value(row.out_of_sample_excess_return_percent, "%")}／${value(row.out_of_sample_trades)} 筆／帳戶回撤 ${value(row.out_of_sample_realized_equity_drawdown_percent, "%")}`;
      return `<tr><td>${row.name}</td><td>${value(row.trades)}</td><td>${value(row.win_rate_percent, "%")}</td><td>${value(row.average_net_return_percent, "%")}</td><td>${oos}；僅研究，不自動選參數</td></tr>`;
    }).join("") || '<tr><td colspan="5">沒有可用結果。</td></tr>';
    $("#parameterStudyDisclosure").textContent = `${data.test_family?.disclosure || "測試家族揭露不足；不得選擇參數。"} ${data.drawdown_disclosure || ""}`;
  }
  function renderFactorAblation(data) {
    $("#factorAblationRows").innerHTML = (data.results || []).map(row => `<tr><td>${row.name}</td><td>${value(row.allocation_matched_excess_return_percent, "%")}</td><td>${value(row.out_of_sample_periods)}</td><td>${value(row.out_of_sample_allocation_matched_excess_return_percent, "%")}</td><td>${value(row.max_drawdown_percent, "%")}</td></tr>`).join("") || '<tr><td colspan="5">沒有可用結果。</td></tr>';
  }
  function renderWalkForward(data) {
    $("#walkForwardRows").innerHTML = (data.folds || []).map(row => `<tr><td>${row.start_date}</td><td>${row.end_date}</td><td>${value(row.oos_trades)}</td><td>${value(row.oos_excess_return_percent, "%")}</td><td>purge ${row.purge_sessions}／embargo ${row.embargo_sessions_after_fold}</td><td>${row.benchmark_status || "資料不足"}</td></tr>`).join("") || '<tr><td colspan="6">資料不足或尚未執行。</td></tr>';
  }
  function renderTechnicalGovernance(data) {
    const ruleRows = (data.rules || []).map(rule => `<tr><td>${rule.name}</td><td>${rule.status}</td><td>${rule.market_regime}</td><td>${rule.entry}</td><td>${rule.exit}</td><td>${rule.risk}</td><td>${rule.decision_use}</td></tr>`).join("");
    const controls = (data.required_controls || []).map(item => `<li>${item}</li>`).join("");
    const promotion = (data.promotion_requirements || []).map(item => `<li>${item}</li>`).join("");
    const evidenceRows = (data.evidence_matrix || []).map(row => `<tr><td>${row.strategy}</td><td>${row.pit_costs_limits}</td><td>${row.oos_matched_benchmark}</td><td>${row.walk_forward_purge}</td><td>${row.paper_forward}</td><td>${row.live_decision}</td></tr>`).join("");
    $("#technicalGovernance").innerHTML = `<p class="unit-note">${data.source || "研究規格"}；${data.formal_recommendation_allowed ? "可作正式推薦" : "不作正式推薦"}。</p><div class="table-scroll"><table><thead><tr><th>規則</th><th>狀態</th><th>市場狀態</th><th>進場</th><th>出場</th><th>風控</th><th>目前用途</th></tr></thead><tbody>${ruleRows}</tbody></table></div><h3>策略證據矩陣</h3><div class="table-scroll"><table><thead><tr><th>策略</th><th>PIT／成本／限制</th><th>樣本外同曝險</th><th>Walk-forward／隔離</th><th>紙上前瞻</th><th>正式決策</th></tr></thead><tbody>${evidenceRows}</tbody></table></div><div class="research-governance-lists"><div><strong>必要控制</strong><ul>${controls}</ul></div><div><strong>升級門檻</strong><ul>${promotion}</ul></div></div>`;
  }
  function renderExecutionAssumptions(data) {
    const assumptions = (data.assumptions || []).map(row => `<tr><td>${row.topic}</td><td>${row.detail}</td></tr>`).join("");
    const nonClaims = (data.non_claims || []).map(item => `<li>${item}</li>`).join("");
    $("#executionAssumptions").innerHTML = `<p class="unit-note">${data.scope || "資料範圍未揭露"}；${data.formal_recommendation_allowed ? "可作正式推薦" : "不作正式推薦"}。</p><div class="table-scroll"><table><thead><tr><th>項目</th><th>預先宣告假設</th></tr></thead><tbody>${assumptions}</tbody></table></div><div class="research-governance-lists"><div><strong>不可作出的宣稱</strong><ul>${nonClaims}</ul></div></div>`;
  }
  function renderEmaAdxStudy(data) {
    const oos = data.out_of_sample || {};
    const benchmark = data.out_of_sample_allocation_matched_benchmark || {};
    const evidence = benchmark.excess_return_percent == null
      ? (benchmark.status || "資料不足")
      : `同曝險超額 ${value(benchmark.excess_return_percent, "%")}（TAIEX 收盤代理）`;
    $("#emaAdxRows").innerHTML = `<tr><td>${data.strategy}</td><td>${value(data.trades)}</td><td>${value(data.portfolio_simulation?.net_return_percent, "%")}</td><td>${oos.start_date || "資料不足"}</td><td>${value(oos.trades)}</td><td>${value(oos.portfolio_simulation?.net_return_percent, "%")}</td><td>${evidence}；僅研究，不影響今日決策</td></tr>`;
  }
  function renderPaperStrategies(data) {
    $("#paperStrategyRows").innerHTML = (data.candidates || []).map(row => {
      const latest = row.latest || {};
      const metrics = row.metrics || {};
      return `<tr><td>${row.strategy_key}<br><small>${row.strategy_version}</small></td><td>${row.status}</td><td>${row.evidence_status}</td><td>${value(row.forward_months)}</td><td>${value(metrics.return_percent, "%")} / ${value(metrics.benchmark_return_percent, "%")} / ${value(metrics.excess_return_percent, "%")}</td><td>${value(metrics.max_drawdown_percent, "%")}</td><td>${value(row.total_transaction_costs)}</td><td>${value(row.pending_orders)}</td></tr>`;
    }).join("") || '<tr><td colspan="8">尚未建立紙上績效。</td></tr>';
  }
  async function refreshPaperStrategies() {
    renderPaperStrategies(await api("/research/paper-strategies"));
  }
  async function refreshHistory() {
    const items = await api("/research/experiments");
    renderHistory(items);
    $("#researchStatus").textContent = `已載入 ${items.length} 筆可稽核實驗。`;
  }
  $("#runRankingBacktest").addEventListener("click", async () => {
    const button = $("#runRankingBacktest"); button.disabled = true;
    $("#rankingBacktestSummary").textContent = "正在建立背景回測工作…";
    clearRankingBacktestRows("本次回測執行中；舊結果已清除。");
    try {
      const params = new URLSearchParams({
        start_date: $("#rankingBacktestStart").value,
        frequency: $("#rankingBacktestFrequency").value,
        top_n: "10",
        minimum_full_factor_symbols: "50",
        require_complete_factor_coverage: "true",
        commission_bps: $("#rankingBacktestCommission").value,
        sell_tax_bps: $("#rankingBacktestSellTax").value,
        slippage_bps: $("#rankingBacktestSlippage").value,
      });
      if ($("#rankingBacktestEnd").value) params.set("end_date", $("#rankingBacktestEnd").value);
      const started = await api(`/research/jobs/short-term-ranking-backtest?${params}`, {method: "POST"});
      renderRankingBacktest(await pollRankingBacktestJob(started.job));
    } catch (error) {
      $("#rankingBacktestSummary").textContent = `回測失敗：${error.message}`;
      clearRankingBacktestRows("本次回測沒有新結果；舊結果已清除，請重新執行。");
    } finally { button.disabled = false; }
  });
  $("#runExperiment").addEventListener("click", async () => {
    const button = $("#runExperiment"); button.disabled = true;
    $("#researchStatus").textContent = "正在執行 walk-forward 實驗；不會影響正式推薦…";
    try {
      const params = new URLSearchParams({min_score: $("#experimentScore").value, top_n: $("#experimentTopN").value});
      if ($("#experimentOos").value) params.set("out_of_sample_start", $("#experimentOos").value);
      const data = await api(`/research/experiments/market-strategy?${params}`, {method: "POST"});
      $("#researchStatus").textContent = `已保存實驗 #${data.experiment.id}，狀態：${data.experiment.status}。`;
      await refreshHistory();
    } catch (error) { $("#researchStatus").textContent = error.message; }
    finally { button.disabled = false; }
  });
  $("#runParameterStudy").addEventListener("click", async () => {
    const button = $("#runParameterStudy"); button.disabled = true;
    $("#researchStatus").textContent = "已建立三組預先宣告技術研究；正在背景執行…";
    try {
      const started = await api("/research/jobs/parameter-study", {method: "POST"});
      const jobId = started.job.id;
      while (true) {
        await new Promise(resolve => setTimeout(resolve, 1200));
        const job = await api(`/research/jobs/${jobId}`);
        if (job.status === "completed") { renderStudy(job.result.result); $("#researchStatus").textContent = `技術研究已保存為實驗 #${job.result.experiment.id}：${job.result.experiment.status}；結果不會自動套用。`; await refreshHistory(); break; }
        if (job.status === "failed") throw new Error(job.error || "背景研究失敗");
        $("#researchStatus").textContent = "背景研究仍在執行；可繼續瀏覽其他頁面。";
      }
    } catch (error) { $("#researchStatus").textContent = error.message; }
    finally { button.disabled = false; }
  });
  $("#runBreakoutExperiment").addEventListener("click", async () => {
    $("#researchStatus").textContent = "正在執行並保存固定突破策略的樣本外實驗…";
    try {
      const data = await api("/research/experiments/technical-breakout", {method: "POST"});
      $("#researchStatus").textContent = `已保存突破策略實驗 #${data.experiment.id}：${data.experiment.status}；尚未具正式推薦資格。`;
      await refreshHistory();
    } catch (error) { $("#researchStatus").textContent = error.message; }
  });
  $("#runBreakoutWalkForward").addEventListener("click", async () => {
    const button = $("#runBreakoutWalkForward"); button.disabled = true;
    $("#researchStatus").textContent = "已建立固定規則 Walk-forward 研究；正在背景執行…";
    try {
      const started = await api("/research/jobs/breakout-walk-forward", {method: "POST"});
      while (true) {
        await new Promise(resolve => setTimeout(resolve, 1200));
        const job = await api(`/research/jobs/${started.job.id}`);
        if (job.status === "completed") { renderWalkForward(job.result.result); $("#researchStatus").textContent = `突破 Walk-forward 已保存為實驗 #${job.result.experiment.id}：${job.result.experiment.status}；不會改變正式規則。`; await refreshHistory(); break; }
        if (job.status === "failed") throw new Error(job.error || "Walk-forward 研究失敗");
      }
    } catch (error) { $("#researchStatus").textContent = error.message; }
    finally { button.disabled = false; }
  });
  $("#runEmaAdxStudy").addEventListener("click", async () => {
    $("#researchStatus").textContent = "正在執行固定 EMA／ADX／ATR 樣本外研究…";
    try {
      const data = await api("/research/experiments/ema-adx", {method: "POST"});
      renderEmaAdxStudy(data.result);
      $("#researchStatus").textContent = `已保存 EMA／ADX／ATR 實驗 #${data.experiment.id}：${data.experiment.status}；尚未具正式推薦資格。`;
      await refreshHistory();
    }
    catch (error) { $("#researchStatus").textContent = error.message; }
  });
  $("#runBollingerRsiExperiment").addEventListener("click", async () => {
    $("#researchStatus").textContent = "正在執行並保存固定布林／RSI 均值回歸實驗…";
    try {
      const data = await api("/research/experiments/bollinger-rsi", {method: "POST"});
      $("#researchStatus").textContent = `已保存布林／RSI 實驗 #${data.experiment.id}：${data.experiment.status}；尚未具正式推薦資格。`;
      await refreshHistory();
    } catch (error) { $("#researchStatus").textContent = error.message; }
  });
  $("#runFactorAblation").addEventListener("click", async () => {
    $("#researchStatus").textContent = "正在比較固定的研究權重；不會修改正式模型…";
    try { renderFactorAblation(await api("/research/factor-ablation")); $("#researchStatus").textContent = "因子消融研究已完成；結果僅供研究。"; }
    catch (error) { $("#researchStatus").textContent = error.message; }
  });
  $("#runPaperValuation").addEventListener("click", async () => {
    $("#researchStatus").textContent = "正在更新鎖定候選的紙上帳本…";
    try { await api("/research/paper-strategies/valuation", {method: "POST"}); await refreshPaperStrategies(); $("#researchStatus").textContent = "紙上帳本已更新；正式推薦未受影響。"; }
    catch (error) { $("#researchStatus").textContent = error.message; }
  });
  Promise.all([refreshHistory(), refreshPaperStrategies(), api("/research/technical-governance").then(renderTechnicalGovernance), api("/research/execution-assumptions").then(renderExecutionAssumptions)]).catch(error => { $("#researchStatus").textContent = error.message; });
})();
