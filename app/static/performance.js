(() => {
  const $ = selector => document.querySelector(selector);
  const number = (value, suffix = "") => value == null ? "—" : `${Number(value).toLocaleString("zh-TW", { maximumFractionDigits: 2 })}${suffix}`;
  const signed = value => value == null ? "—" : `${Number(value) >= 0 ? "+" : ""}${number(value, "%")}`;
  let toastTimer;

  function toast(message, error = false) {
    const el = $("#toast");
    el.textContent = message;
    el.className = `toast show${error ? " error" : ""}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = "toast"; }, 3500);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, options);
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : {}; }
    catch { throw new Error(`伺服器回傳非預期內容（${response.status}）`); }
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(item=>item.msg || JSON.stringify(item)).join("；") : data.detail;
      throw new Error(detail || `請求失敗（${response.status}）`);
    }
    return data;
  }

  function metric(label, value, className = "") {
    return `<article class="${className}"><span>${label}</span><strong>${value}</strong></article>`;
  }

  function setTable(title, eyebrow, headers, rows) {
    $("#performanceTableTitle").textContent = title;
    $("#performanceTableEyebrow").textContent = eyebrow;
    $("#performanceHead").innerHTML = `<tr>${headers.map(item => `<th>${item}</th>`).join("")}</tr>`;
    $("#performanceRows").innerHTML = rows || `<tr><td colspan="${headers.length}">目前沒有可顯示的回測結果。</td></tr>`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[character]));
  }

  function attributionTable(title, headers, rows) {
    const cells = rows.length ? rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${headers.length}">資料不足</td></tr>`;
    return `<div class="table-scroll"><h3>${title}</h3><table><thead><tr>${headers.map(header => `<th>${header}</th>`).join("")}</tr></thead><tbody>${cells}</tbody></table></div>`;
  }

  function renderStrategyAttribution(data) {
    const section = $("#strategyAttribution");
    const report = data.attribution;
    if (!report) { section.hidden = true; return; }
    const regime = (report.by_market_regime || []).map(row => [escapeHtml(row.regime), number(row.periods), number(row.average_cash_percent, "%"), signed(row.total_return_percent), signed(row.benchmark_total_return_percent), signed(row.excess_return_percent)]);
    const industries = (report.by_industry || []).map(row => [escapeHtml(row.label), number(row.positions), number(row.average_return_percent, "%"), signed(row.contribution_percent)]);
    const stocks = (report.by_stock || []).slice(0, 12).map(row => [escapeHtml(row.label), number(row.positions), number(row.average_return_percent, "%"), signed(row.contribution_percent)]);
    const factors = (report.factor_score_return_correlation || []).map(row => [escapeHtml(row.factor), number(row.sample_size), number(row.score_return_correlation)]);
    $("#strategyAttributionContent").innerHTML = [
      attributionTable("市場狀態（相同股票曝險基準）", ["狀態", "期數", "平均現金", "策略", "同曝險基準", "超額"], regime),
      attributionTable("產業貢獻", ["產業", "持倉次數", "平均報酬", "加權貢獻"], industries),
      attributionTable("個股貢獻（前 12）", ["股票", "持倉次數", "平均報酬", "加權貢獻"], stocks),
      attributionTable("因子分數與後續報酬相關", ["因子", "樣本", "相關係數"], factors),
      `<p class="warning-copy">${escapeHtml(report.methodology)}</p>`,
    ].join("");
    section.hidden = false;
  }

  function renderStrategy(data) {
    $("#performanceSummary").innerHTML = [
      metric("回測期數", number(data.periods)),
      metric("策略累積報酬", signed(data.total_return_percent), data.total_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("加權指數累積報酬", signed(data.benchmark_total_return_percent), data.benchmark_total_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("相同現金比例指數", signed(data.allocation_matched_benchmark?.benchmark_total_return_percent), data.allocation_matched_benchmark?.benchmark_total_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("選股相對報酬", signed(data.allocation_matched_benchmark?.excess_return_percent), data.allocation_matched_benchmark?.excess_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("相對指數超額", signed(data.excess_return_percent), data.excess_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("最大回撤", signed(data.max_drawdown_percent), "negative-text"),
      metric("月波動度", number(data.monthly_volatility_percent, "%")),
      metric("單次換手成本假設", number(data.transaction_cost_assumption_bps, " bps")),
    ].join("");
    const rows = (data.outcomes || []).slice().reverse().map(row => `<tr>
      <td>${row.date}</td><td>${row.next_date}</td><td>${number(row.cash_percent, "%")}</td>
      <td>${number(row.selected)}</td><td class="${row.strategy_return_percent >= 0 ? "positive-text" : "negative-text"}">${signed(row.strategy_return_percent)}</td>
      <td class="${row.benchmark_return_percent >= 0 ? "positive-text" : "negative-text"}">${signed(row.benchmark_return_percent)}</td>
      <td>${number(row.equity, "×")}</td><td>${number(row.benchmark_equity, "×")}</td></tr>`).join("");
    setTable("市場策略逐期結果", "MARKET STRATEGY WALK-FORWARD", ["起始日", "下一期", "現金", "選股數", "策略報酬", "指數報酬", "策略淨值", "指數淨值"], rows);
    const oos = data.out_of_sample;
    const oosMatched = data.out_of_sample_allocation_matched_benchmark;
    const oosSummary = oos && oos.periods
      ? `樣本外（${data.out_of_sample_start} 起）${oos.periods} 期：策略 ${signed(oos.total_return_percent)}、全額指數 ${signed(oos.benchmark_total_return_percent)}、相同現金比例指數 ${signed(oosMatched?.benchmark_total_return_percent)}、選股相對報酬 ${signed(oosMatched?.excess_return_percent)}、最大回撤 ${signed(oos.max_drawdown_percent)}。`
      : data.out_of_sample_start ? `樣本外起點 ${data.out_of_sample_start} 之後尚無足夠期數。` : "未設定樣本外起點；目前只顯示全期間結果。";
    $("#performanceStatus").textContent = data.periods
      ? `以每月資料點執行 ${data.periods} 期；最低分數 ${data.min_score}，每期最多選 ${data.top_n} 檔。`
      : "市場指數歷史資料不足，尚無法執行策略回測。";
    $("#performanceStatus").textContent += ` ${oosSummary}`;
    renderStrategyAttribution(data);
  }

  function renderVnextWalkForward(data) {
    const coverage = data.eligibility_coverage || {};
    $("#performanceSummary").innerHTML = [
      metric("Walk-forward folds", number(data.signals)),
      metric("Matured positions", number(data.matured_positions)),
      metric("Average net return", signed(data.average_net_return_percent), data.average_net_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("Win rate", number(data.win_rate_percent, "%")),
      metric("Purged signals", number(data.purged_signals)),
      metric("Liquidity threshold", number(data.minimum_daily_turnover)),
      metric("Eligible folds", number(coverage.folds_with_eligible_stocks)),
    ].join("");
    const rows = (data.outcomes || []).slice().reverse().map(row => `<tr><td>${row.signal_date}</td><td>${row.entry_date}</td><td>${row.exit_date}</td><td>${row.symbol}</td><td>${number(row.score)}</td><td>${signed(row.net_return_percent)}</td><td>${number(row.cash_dividend)}</td></tr>`).join("");
    setTable("vNext point-in-time Walk-forward", "PIT / COSTS / LIQUIDITY", ["Signal", "Entry", "Exit", "Stock", "Score", "Net return", "Cash dividend"], rows);
    $("#performanceStatus").textContent = coverage.status === "insufficient_historical_coverage"
      ? `No vNext result is shown because historical eligibility coverage is insufficient: ${Object.entries(coverage.missing_summary || {}).map(([name, count]) => `${name} ${count}`).join(", ")}.`
      : data.folds?.length ? "Historical simulation: availability lags, costs, slippage, liquidity and cash dividends are included." : "No eligible point-in-time folds were available for the chosen period.";
  }

  function renderTechnicalBreakout(data) {
    const quality = data.parameters || {};
    const exitSummary = (data.diagnostics?.by_exit_reason || []).map(row => `${row.group}: ${signed(row.average_net_return_percent)} (${number(row.trades)} trades)`).join(" | ");
    $("#performanceSummary").innerHTML = [
      metric("Signals", number(data.signals)), metric("Trades", number(data.trades)),
      metric("Liquidity excluded", number(data.liquidity_excluded)), metric("Win rate", number(data.win_rate_percent, "%")),
      metric("Average net return", signed(data.average_net_return_percent), data.average_net_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("Quality gate", `>=${number(quality.min_breakout_percent, "%")} / ${number(quality.volume_multiple, "x")}`),
    ].join("");
    const rows = (data.outcomes || []).slice().reverse().map(row => `<tr><td>${row.signal_date}</td><td>${row.entry_date}</td><td>${row.exit_date}</td><td>${row.symbol}</td><td>${row.exit_reason}</td><td>${number(row.atr)}</td><td class="${row.net_return_percent >= 0 ? "positive-text" : "negative-text"}">${signed(row.net_return_percent)}</td></tr>`).join("");
    setTable("Technical breakout research", "NEXT-SESSION ENTRY / COSTS / ATR", ["Signal", "Entry", "Exit", "Stock", "Exit", "ATR", "Net return"], rows);
    $("#performanceStatus").textContent = data.trades
      ? `Independent-trade research only. Exit diagnostic: ${exitSummary}. Not a portfolio equity curve or trading recommendation.`
      : "No eligible technical-breakout trades were found.";
  }

  function renderHistorical(data) {
    $("#performanceSummary").innerHTML = [
      metric("已完成訊號", number(data.total_signals)), metric("評分日期", number(data.scoring_dates)),
      metric("入選股票數", number(data.unique_symbols)), metric("勝率", number(data.win_rate_percent, "%")),
      metric("平均報酬", signed(data.average_return_percent), data.average_return_percent >= 0 ? "positive-text" : "negative-text"),
      metric("中位數報酬", signed(data.median_return_percent)), metric("平均最大回撤", signed(data.average_max_drawdown_percent), "negative-text"),
    ].join("");
    const rows = (data.outcomes || []).map(row => `<tr><td><a href="/stock/?symbol=${encodeURIComponent(row.symbol)}"><strong>${row.snapshot_date}</strong><br>${row.symbol} ${row.name || ""}</a></td><td>#${row.rank}</td><td>${number(row.score)}</td><td>${number(row.close)}</td><td class="${row.return_percent >= 0 ? "positive-text" : "negative-text"}">${signed(row.return_percent)}</td><td class="negative-text">${signed(row.max_drawdown_percent)}</td></tr>`).join("");
    setTable("歷史選股結果", "HISTORICAL SIGNALS", ["評分日／股票", "排名", "分數", "收盤價", "後續報酬", "最大回撤"], rows);
    $("#performanceStatus").textContent = data.total_signals ? `共 ${data.scoring_dates} 個評分日，依每期前 ${data.top_n} 檔與最低分數 ${data.min_score} 回測。` : "尚無足夠的歷史基本面與價格資料可產生結果。";
  }

  function renderLive(data) {
    $("#performanceSummary").innerHTML = [metric("所有訊號", number(data.total_signals)), metric("已成熟", number(data.matured_signals)), metric("待觀察", number(data.pending_signals)), metric("勝率", number(data.win_rate_percent, "%")), metric("平均報酬", signed(data.average_return_percent)), metric("平均超額", signed(data.average_excess_return_percent)), metric("平均最大回撤", signed(data.average_max_drawdown_percent), "negative-text")].join("");
    const rows = (data.outcomes || []).map(row => `<tr><td><a href="/stock/?symbol=${encodeURIComponent(row.symbol)}"><strong>${row.snapshot_date}</strong><br>${row.symbol} ${row.name || ""}</a></td><td>#${row.rank}</td><td>${number(row.score)}</td><td>${number(row.close)}</td><td class="${row.return_percent >= 0 ? "positive-text" : "negative-text"}">${signed(row.return_percent)}</td><td>${signed(row.excess_return_percent)}</td><td class="negative-text">${signed(row.max_drawdown_percent)}</td></tr>`).join("");
    setTable("已儲存推薦快照", "LIVE MODEL SNAPSHOTS", ["快照日／股票", "排名", "分數", "收盤價", "後續報酬", "超額報酬", "最大回撤"], rows);
    $("#performanceStatus").textContent = data.total_signals ? `目前有 ${data.matured_signals} 個成熟觀察值與 ${data.pending_signals} 個待觀察訊號。` : "尚未建立推薦快照；可按右上方按鈕建立今日資料。";
  }

  function renderFactors(data) {
    $("#performanceSummary").innerHTML = [
      metric("成熟樣本", number(data.matured_signals)),
      metric("可檢驗因子", number(data.testable_factors)),
      metric("最低樣本門檻", number(data.minimum_sample)),
      metric("觀察期", number(data.horizon, " 日")),
    ].join("");
    const factorRows = (data.factors || []).map(row => `<tr><td>${row.label}</td><td>${number(row.sample_size)}</td><td>${number(row.information_coefficient)}</td><td>${signed(row.high_minus_low_return_percent)}</td><td>${row.status === "testable" ? "可檢驗" : "樣本不足"}</td></tr>`);
    const sensitivityRows = (data.weight_sensitivity || []).map(row => `<tr><td>敏感度：${row.label}</td><td>${number(row.sample_size)}</td><td>${number(row.rank_ic)}</td><td>${signed(row.top_quintile_return_percent)}</td><td>${row.status === "testable" ? "可初步比較" : "樣本不足"}</td></tr>`);
    const regimeRows = (data.market_regimes || []).map(row => `<tr><td>市場：${row.regime}</td><td>${number(row.sample_size)}</td><td>勝率 ${number(row.win_rate_percent,"%")}</td><td>${signed(row.average_return_percent)}</td><td>分狀態觀察</td></tr>`);
    const rows = [...factorRows,...sensitivityRows,...regimeRows].join("");
    setTable("因子有效性", "FACTOR VALIDATION", ["因子", "樣本", "等級相關 IC", "高分－低分報酬", "狀態"], rows);
    $("#performanceStatus").textContent = data.conclusion;
  }

  function render(data) {
    if (data.mode === "vnext_walk_forward") renderVnextWalkForward(data);
    else if (data.mode === "technical_breakout_backtest") renderTechnicalBreakout(data);
    else if (data.mode === "factor_validation") renderFactors(data);
    else if (data.mode === "strategy_backtest") renderStrategy(data);
    else if (data.mode === "historical_backtest") renderHistorical(data);
    else renderLive(data);
    if (data.mode !== "strategy_backtest") $("#strategyAttribution").hidden = true;
    $("#performanceLimitations").innerHTML = (data.limitations || []).map(item => `<span>• ${item}</span>`).join(" ");
  }

  async function loadPaperGovernance() {
    try {
      const data = await api("/research/paper-strategies");
      const rows = data.candidates || [];
      const summary = rows.map(row => `${row.strategy_key}: ${row.evidence_status}（前瞻 ${row.forward_months || 0} 個月）`).join("；");
      $("#paperGovernanceStatus").textContent = summary
        ? `鎖定研究候選：${summary}。候選策略不會自動修改正式推薦權重。`
        : "尚未建立鎖定研究候選；模型成績不代表紙上策略績效。";
    } catch (error) { $("#paperGovernanceStatus").textContent = "候選策略治理狀態暫時無法讀取。"; }
  }

  function syncControls() {
    const mode = $("#performanceMode").value;
    const report = $("#recommendationReport").value;
    const resolvedMode = mode === "recommendations" ? report : mode;
    $("#recommendationReportControl").hidden = mode !== "recommendations";
    $("#profileControl").hidden = !["live", "factors"].includes(resolvedMode);
    $("#horizonControl").hidden = ["strategy", "technical"].includes(resolvedMode);
    $("#minScoreControl").hidden = !["strategy", "backtest", "live"].includes(resolvedMode);
    $("#topNControl").hidden = !["strategy", "vnext", "backtest"].includes(resolvedMode);
    $("#outOfSampleControl").hidden = resolvedMode !== "strategy";
    $("#slippageControl").hidden = !["strategy", "vnext", "technical"].includes(resolvedMode);
    $("#turnoverControl").hidden = !["strategy", "vnext", "technical"].includes(resolvedMode);
    $("#embargoControl").hidden = resolvedMode !== "vnext";
    return resolvedMode;
  }

  async function load() {
    const selectedMode = $("#performanceMode").value;
    const mode = selectedMode === "recommendations" ? $("#recommendationReport").value : selectedMode;
    const profile = $("#performanceProfile").value;
    const horizon = $("#performanceHorizon").value;
    const score = $("#performanceMinScore").value;
    const topN = $("#performanceTopN").value;
    const outOfSampleStart = $("#outOfSampleStart").value;
    const slippageBps = $("#slippageBps").value;
    const minimumTurnover = $("#minimumTurnover").value;
    const embargoSessions = $("#embargoSessions").value;
    syncControls();
    $("#performanceStatus").textContent = "正在載入模型成績⋯";
    try {
      const url = mode === "factors" ? `/performance/factors?profile=${profile}&horizon=${horizon}`
        : mode === "strategy" ? `/performance/strategy-backtest?min_score=${score}&top_n=${topN}&slippage_bps=${slippageBps}&min_turnover=${minimumTurnover}${outOfSampleStart ? `&out_of_sample_start=${outOfSampleStart}` : ""}`
        : mode === "vnext" ? `/performance/vnext-walk-forward?horizon=${horizon}&top_n=${topN}&slippage_bps=${slippageBps}&min_turnover=${minimumTurnover}&embargo_sessions=${embargoSessions}`
        : mode === "technical" ? `/performance/technical-breakout-backtest?slippage_bps=${slippageBps}&min_turnover=${minimumTurnover}`
        : mode === "backtest" ? `/performance/backtest?horizon=${horizon}&min_score=${score}&top_n=${topN}`
          : `/performance/summary?profile=${profile}&horizon=${horizon}&min_score=${score}`;
      render(await api(url));
      loadPaperGovernance();
    } catch (error) { $("#performanceStatus").textContent = error.message; }
  }

  async function capture() {
    const button = $("#captureSnapshotButton");
    button.disabled = true; button.textContent = "建立中⋯";
    try { const result = await api("/performance/snapshot", { method: "POST" }); toast(`已建立 ${result.total_rows} 筆推薦快照`); await load(); }
    catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "建立今日推薦快照"; }
  }

  $("#reloadPerformanceButton").addEventListener("click", load);
  $("#captureSnapshotButton").addEventListener("click", capture);
  ["#performanceMode", "#recommendationReport", "#performanceProfile", "#performanceHorizon", "#outOfSampleStart", "#slippageBps", "#minimumTurnover", "#embargoSessions"].forEach(id => $(id).addEventListener("change", load));
  api("/health").then(() => { $("#apiStatus").className = "status-dot online"; $("#apiStatus").innerHTML = "<i></i>服務正常"; }).catch(() => {});
  load();
})();
