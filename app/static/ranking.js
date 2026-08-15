(() => {
  const status = document.querySelector("#rankingStatus");
  const rules = document.querySelector("#rankingRules");
  const list = document.querySelector("#rankingList");
  const positionArea = document.querySelector("#privatePositionArea");
  const positionList = document.querySelector("#positionList");
  const positionSummary = document.querySelector("#positionSummary");
  const localEditing = ["127.0.0.1", "localhost", "::1"].includes(window.location.hostname);
  const escapeHtml = value => String(value ?? "資料不足").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = value => value == null ? "資料不足" : new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 2 }).format(value);
  const percent = value => value == null ? "資料不足" : `${number(value)}%`;
  const money = value => value == null ? "資料不足" : `${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 0 }).format(value)} 元`;
  const gradeText = grade => ({ A: "A｜優先關注", B: "B｜次優先關注", C: "C｜一般觀察", D: "D｜暫停關注" }[grade] || "資料不足");
  const operationText = status => ({ ready: "基本面與技術條件均完成", ready_with_risk: "基本面與技術條件完成，但有風險", waiting_trigger: "基本面通過，等待技術觸發", reject_rr: "不執行：RR不足", blocked_overextended: "不追價：短線過度延伸", blocked_fundamental: "不建議買進：基本面未通過", blocked: "不執行：資料、事件或成交風險" }[status] || "操作狀態不足");
  const operationPriority = { ready: 0, ready_with_risk: 1 };
  const marketModeText = mode => ({ trend: "趨勢偏多", range: "區間整理", defensive: "防守", unavailable: "資料尚未對齊" }[mode] || mode || "資料不足");
  const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());

  async function positionApi(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "持倉資料無法處理");
    return data;
  }

  function toast(message, isError = false) {
    const element = document.querySelector("#rankingToast");
    element.textContent = message;
    element.classList.remove("hidden", "error");
    if (isError) element.classList.add("error");
    requestAnimationFrame(() => element.classList.add("show"));
    setTimeout(() => element.classList.remove("show"), 3200);
  }

  function card(item, index) {
    const plan = item.trade_plan || {};
    const indicators = item.indicators || {};
    const flow = item.institutional_flow || {};
    const fundamental = item.fundamental_snapshot || {};
    const scores = item.attention_score_components || item.research_score_components || {};
    const blockers = (plan.blocking_reasons || []).map(escapeHtml);
    const risks = (item.ranking_risks || []).map(escapeHtml);
    const evidence = (item.ranking_evidence || []).map(escapeHtml);
    const macdDirection = indicators.macd_histogram_change == null ? "資料不足" : indicators.macd_histogram_change > 0 ? "柱狀體增強" : "柱狀體轉弱";
    const triggered = plan.analysis_status === "PASS";
    const tradeEvaluation = triggered
      ? `參考進場 ${number(plan.reference_entry)}｜最高允許 ${number(plan.maximum_entry_price)}｜停損 ${number(plan.stop)}｜獨立目標 ${number(plan.planned_target)}｜成本後 RR 1：${number(plan.cost_adjusted_risk_reward)}（最低 1：${number(plan.required_rr)}）`
      : "進場尚未觸發；真正進場價、停損與 RR 必須等訊號成立後重新計算";
    return `<a class="dashboard-action-card ${item.candidate_grade === "A" ? "accumulate" : "wait"}" href="/stock/?symbol=${encodeURIComponent(item.symbol)}">
      <div>
        <strong>第 ${index + 1} 名｜${escapeHtml(item.symbol)} ${escapeHtml(item.name)}</strong>
        <small>${escapeHtml(gradeText(item.attention_grade || item.candidate_grade))}｜關注分數 ${number(item.attention_score ?? item.research_priority_score)}／100｜${escapeHtml(item.observation_status)}</small>
        <small>關注分數：趨勢 ${number(scores.trend)}｜相對強度 ${number(scores.relative_strength)}｜流動性 ${number(scores.liquidity)}｜法人確認 ${number(scores.institutional_confirmation)}｜風險扣分 ${number(scores.risk_penalty)}</small>
        <small>趨勢：MA5 ${number(indicators.sma_5)}／MA10 ${number(indicators.sma_10)}／MA20 ${number(indicators.sma_20)}｜5 日 ${percent(indicators.return_5d_percent)}、10 日 ${percent(indicators.return_10d_percent)}</small>
        <small>相對強度：5 日對大盤 ${percent(indicators.relative_market_5d_percent)}｜5 日對產業 ${percent(indicators.relative_industry_5d_percent)}｜產業廣度 ${percent(item.industry_context?.breadth_positive_5d_percent)}</small>
        <small>量價與動能：5 日量比 ${number(indicators.volume_ratio_5)}｜20 日量比 ${number(indicators.volume_ratio_20)}｜RSI ${number(indicators.rsi_14)}｜MACD ${escapeHtml(macdDirection)}</small>
        <small>籌碼：外資 5 日 ${number(flow.foreign_net_5d)}｜投信 5 日 ${number(flow.trust_net_5d)}｜資料日 ${escapeHtml(flow.as_of)}</small>
        <small>基本面門檻：同訊號日本益比 ${number(fundamental.pe_ratio)}（上限 ${number(fundamental.pe_ceiling)}）｜股價淨值比 ${number(fundamental.pb_ratio)}｜月營收年增 ${percent(fundamental.revenue_yoy_percent)}</small>
        <small>獲利品質：本業獲利年增 ${percent(fundamental.operating_income_yoy_percent)}｜本業／稅後淨利代理值 ${percent(fundamental.core_earnings_ratio_percent)}｜現金流安全值 ${money(fundamental.free_cash_flow_safety_value)}</small>
        <small>操作狀態：${escapeHtml(operationText(item.operation_status))}｜${escapeHtml(item.operation_reason)}</small>
        <small>交易評估：${tradeEvaluation}</small>
        ${triggered ? `<small>目標依據：${escapeHtml(plan.planned_target_basis)}｜最低 RR 所需價 ${number(plan.minimum_target_required_rr_after_cost)} 僅為門檻，不是預測目標</small>` : ""}
        <small>流動性上限：單檔以 20 日平均成交金額 1% 計，約 ${money(plan.liquidity?.max_position_value_at_1pct_adv)}</small>
        <small>上榜依據：${evidence.join("；") || "通過基本面與流動性安全門檻"}</small>
        <small>操作依據：${blockers.join("；") || risks.join("；") || "條件完成，但策略治理目前只允許紙上追蹤"}</small>
      </div><b>查看完整分析 →</b>
    </a>`;
  }

  function operationCard(item, meta, operationRank, attentionRank, isNewTrigger) {
    const plan = item.trade_plan || {};
    const purchaseButton = localEditing
      ? `<button class="button primary record-purchase" type="button" data-symbol="${escapeHtml(item.symbol)}" data-name="${escapeHtml(item.name)}" data-market="${escapeHtml(item.market)}" data-signal-date="${escapeHtml(meta.signal_date)}" data-strategy-version="${escapeHtml(meta.strategy_version)}" data-entry-price="${escapeHtml(plan.reference_entry)}" data-stop-price="${escapeHtml(plan.stop)}" data-target-price="${escapeHtml(plan.planned_target)}">我已買進</button>`
      : "";
    const triggerLabel = isNewTrigger ? "今日新觸發" : "目前仍符合";
    return `<article class="dashboard-action-card accumulate"><div><strong>可操作第 ${operationRank}｜${escapeHtml(item.symbol)} ${escapeHtml(item.name)}｜${escapeHtml(operationText(item.operation_status))}</strong><small>${triggerLabel}｜原關注名次第 ${attentionRank || "—"}；可操作排序不沿用關注名次。</small><small>${escapeHtml(item.operation_reason)}</small><small>參考進場 ${number(plan.reference_entry)}｜最高允許 ${number(plan.maximum_entry_price)}｜停損 ${number(plan.stop)}｜獨立目標 ${number(plan.planned_target)}｜成本後 RR 1：${number(plan.cost_adjusted_risk_reward)}</small><small>僅供研究驗證；請登記實際成交價，次日跳空仍可能使原計畫失效。</small></div><div class="position-card-actions">${purchaseButton}<a class="button button-link" href="/stock/?symbol=${encodeURIComponent(item.symbol)}">查看計畫</a></div></article>`;
  }

  function positionCard(position) {
    const decision = position.decision || {};
    const actionable = ["reduce_next_open", "exit_next_open"].includes(decision.action);
    const style = decision.action === "exit_next_open" ? "sell" : decision.action === "reduce_next_open" ? "reduce" : decision.action === "data_pending" ? "wait" : "accumulate";
    const action = decision.action === "reduce_next_open" ? "reduce" : "exit";
    const actionButton = actionable && localEditing
      ? `<button class="button primary confirm-execution" type="button" data-symbol="${escapeHtml(position.symbol)}" data-name="${escapeHtml(position.name)}" data-action="${action}" data-shares="${decision.suggested_shares}" data-price="${decision.current_close}" data-reason="${escapeHtml(decision.reason)}">登記已賣出</button>`
      : "";
    const stopText = position.target_reduction_executed
      ? `保本停損 ${number(position.active_stop)}（已完成第一次減碼）`
      : `停損 ${number(position.active_stop)}｜目標 ${number(position.target_price)}`;
    return `<article class="dashboard-action-card ${style}"><div><strong>${escapeHtml(position.symbol)} ${escapeHtml(position.name)}｜${escapeHtml(decision.label)}</strong><small>${escapeHtml(decision.reason)}</small><small>實際買進 ${number(position.entry_price)} × ${number(position.initial_shares)} 股｜剩餘 ${number(position.remaining_shares)} 股｜持有 ${number(decision.holding_sessions)} 個交易日</small><small>最新收盤 ${number(decision.current_close)}（${escapeHtml(decision.price_date)}）｜未實現 ${percent(position.unrealized_return_percent)}｜${stopText}</small><small>訊號日 ${escapeHtml(position.signal_date)}｜實際買進日 ${escapeHtml(position.entry_date)}｜不因跌出排行榜自動賣出</small></div><div class="position-card-actions">${actionButton}<a class="button button-link" href="/stock/?symbol=${encodeURIComponent(position.symbol)}">查看個股</a></div></article>`;
  }

  async function loadPositions() {
    positionArea.classList.remove("hidden");
    try {
      const data = await positionApi("/short-term-positions");
      const editNote = localEditing ? "可在本機登記買進與實際賣出。" : "公開網址為唯讀，交易紀錄請在本機網站登記。";
      positionSummary.textContent = data.active_count
        ? `目前 ${data.active_count} 檔進行中，${data.action_count} 檔有下一交易日賣出動作。資料判定日 ${data.as_of}。${editNote}`
        : `目前沒有已登記的短線持倉。${editNote}`;
      positionList.innerHTML = data.positions.length
        ? data.positions.map(positionCard).join("")
        : '<p class="dashboard-empty">尚未登記短線持倉。</p>';
    } catch (error) {
      positionSummary.textContent = error.message;
      positionList.innerHTML = '<p class="dashboard-empty">持倉資料暫時無法讀取。</p>';
    }
  }

  function signalFollowUpCard(item, expired = false, meta = {}) {
    const current = item.current || {};
    const previous = item.previous || {};
    const gap = current.operation_gap || {};
    const missingChecks = [...(gap.missing_checks || [])];
    const rr = current.trigger_checks?.risk_reward;
    if (rr?.passed === false && !missingChecks.some(check => check.key === "risk_reward")) {
      missingChecks.push({ key: "risk_reward", ...rr });
    }
    const missing = missingChecks.map(missingCheckText).join("；");
    const detail = missing || item.reason || "今日狀態待確認";
    const style = expired ? "sell" : current.operation_status === "ready_with_risk" ? "wait" : "accumulate";
    const plan = previous.trade_plan || {};
    const canRecord = !expired && localEditing && plan.reference_entry && plan.stop && plan.planned_target;
    const purchaseButton = canRecord
      ? `<button class="button primary record-purchase" type="button" data-symbol="${escapeHtml(item.symbol)}" data-name="${escapeHtml(item.name)}" data-market="${escapeHtml(item.market)}" data-signal-date="${escapeHtml(previous.latest_price_date)}" data-strategy-version="${escapeHtml(meta.strategy_version)}" data-entry-price="${escapeHtml(plan.reference_entry)}" data-stop-price="${escapeHtml(plan.stop)}" data-target-price="${escapeHtml(plan.planned_target)}">我已買進</button>`
      : "";
    return `<article class="dashboard-action-card ${style}"><div><strong>${escapeHtml(item.symbol)} ${escapeHtml(item.name)}｜${escapeHtml(item.lifecycle_label)}</strong><small>前次訊號 ${escapeHtml(previous.latest_price_date)}｜前次收盤 ${number(previous.close)}｜今日收盤 ${number(current.close)}</small><small>${escapeHtml(detail)}</small><small>此區追蹤原訊號，不代表已成交或發出賣出指令。</small></div><div class="position-card-actions">${purchaseButton}<a class="button button-link" href="/stock/?symbol=${encodeURIComponent(item.symbol)}">查看個股</a></div></article>`;
  }

  function fundamentalRejectionCard(item) {
    const fundamental = item.fundamental_snapshot || {};
    const reasons = (fundamental.blocking_reasons || []).map(escapeHtml).join("；") || "必要基本面資料不足";
    return `<a class="dashboard-action-card sell" href="/stock/?symbol=${encodeURIComponent(item.symbol)}"><div><strong>${escapeHtml(item.symbol)} ${escapeHtml(item.name)}｜不進入今日操作</strong><small>${reasons}</small><small>訊號日 ${escapeHtml(item.latest_price_date)}｜收盤 ${number(item.close)}｜同訊號日本益比 ${number(fundamental.pe_ratio)}｜本業獲利年增 ${percent(fundamental.operating_income_yoy_percent)}</small><small>即使技術突破成立，也不能覆蓋估值與獲利品質門檻。</small></div><b>查看原因 →</b></a>`;
  }

  function fundamentalPendingCard(item) {
    const fundamental = item.fundamental_snapshot || {};
    const reasons = (fundamental.blocking_reasons || []).map(escapeHtml).join("；") || "財報與估值尚未完成交叉驗證";
    return `<a class="dashboard-action-card wait" href="/stock/?symbol=${encodeURIComponent(item.symbol)}"><div><strong>${escapeHtml(item.symbol)} ${escapeHtml(item.name)}｜資料待同步，不判斷好壞</strong><small>${reasons}</small><small>財報期 ${escapeHtml(fundamental.financial_date)}｜估值資料日 ${escapeHtml(fundamental.valuation_source_date)}｜差異 ${percent(fundamental.pe_cross_check_difference_percent)}</small><small>同步完成前不進入排行榜或今日操作，避免把資料不一致誤認為投資機會。</small></div><b>查看原因 →</b></a>`;
  }

  function missingCheckText(check) {
    if (check.key === "breakout") return `突破：收盤 ${number(check.actual)}，需高於 ${number(check.required_above)}，距離約 ${percent(check.gap_percent)}`;
    if (check.key === "volume") return `量能：目前 ${number(check.actual_ratio)} 倍，需 ${number(check.required_ratio)} 倍，尚差約 ${percent(check.gap_percent)}`;
    if (check.key === "risk_reward") return `RR：目前 1：${number(check.actual)}，最低 1：${number(check.required)}`;
    return check.label || check.key || "條件資料不足";
  }

  function closestCard(item, index) {
    const gap = item.operation_gap || {};
    const missing = gap.missing_checks || [];
    const detail = missing.map(missingCheckText).map(escapeHtml).join("；") || "待次日實際開盤確認";
    const provisional = gap.rr_is_provisional ? "尚未觸發，RR 只供預覽且不列為缺失條件" : "觸發已完成，RR 可正式檢查";
    return `<a class="dashboard-action-card wait" href="/stock/?symbol=${encodeURIComponent(item.symbol)}"><div><strong>接近度 ${index + 1}｜${escapeHtml(item.symbol)} ${escapeHtml(item.name)}</strong><small>${escapeHtml(gradeText(item.attention_grade))}｜關注分數 ${number(item.attention_score)}｜還差 ${number(gap.missing_count)} 項核心條件</small><small>${detail}</small><small>${escapeHtml(provisional)}</small></div><b>查看分析 →</b></a>`;
  }

  function trackingSection(tracking) {
    if (!tracking || !tracking.snapshot_dates?.length) {
      return `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">FORWARD VALIDATION</p><h2>每日榜單前瞻追蹤</h2><p>尚未保存排行榜快照；完成每日收盤同步後會開始累積，既有舊榜單不會事後回填。</p></div></div></section>`;
    }
    const cards = [3, 5, 10].map(horizon => {
      const row = tracking.horizons?.[String(horizon)] || {};
      const result = row.matured_signals
        ? `平均 ${percent(row.average_return_percent)}｜成本後 ${percent(row.average_net_return_after_assumed_cost_percent)}｜勝率 ${percent(row.win_rate_percent)}｜對大盤超額 ${percent(row.average_market_excess_return_percent)}`
        : `成熟 0 筆；${number(row.pending_signals)} 筆仍等待第 ${horizon} 個交易日`;
      return `<div class="dashboard-action-card wait"><div><strong>${horizon} 日後</strong><small>${result}</small><small>成熟 ${number(row.matured_signals)}｜涵蓋 ${number(row.unique_signal_dates)} 個訊號日｜等待 ${number(row.pending_signals)}｜平均最大回撤 ${percent(row.average_max_drawdown_percent)}</small></div></div>`;
    }).join("");
    const assessment = tracking.effectiveness_assessment || {};
    const verdicts = {
      insufficient_data: "證據不足，現在不能判定排行榜有效",
      promising_not_yet_validated: "前瞻結果具潛力，但尚未完成正式驗證",
      mixed_evidence: "結果不一致，暫不支持正式使用",
      forward_evidence_does_not_support_ranking: "目前前瞻證據不支持排行榜",
    };
    const evidenceText = verdicts[assessment.verdict] || "尚無成效判定";
    const latestRun = tracking.ranking_runs?.[0];
    const entered = latestRun?.changes?.entered || [];
    const exited = latestRun?.changes?.exited || [];
    const changeText = latestRun
      ? `最新榜單周轉率 ${percent(latestRun.turnover_percent)}｜新進 ${entered.map(row => escapeHtml(row.symbol)).join("、") || "無"}｜退出 ${exited.map(row => escapeHtml(row.symbol)).join("、") || "無"}`
      : "舊版快照沒有完整的批次換股紀錄；新版快照起才會提供。";
    return `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">FORWARD VALIDATION</p><h2>每日榜單前瞻追蹤</h2><p>已保存 ${tracking.snapshot_dates.length} 個訊號日、${number(tracking.total_signals)} 筆；最新 ${escapeHtml(tracking.snapshot_dates[0])}。未成熟樣本不算 0%。</p><p>${changeText}</p></div></div><div class="decision-gate"><strong>目前判定：${escapeHtml(evidenceText)}</strong><p>${escapeHtml(assessment.criteria || "需累積不可修改的前瞻樣本，並同時比較成本後報酬、大盤與同業。")}</p><a class="text-link" href="/research/">查看嚴格 PIT 歷史回放 →</a></div><div class="dashboard-actions">${cards}</div><p class="unit-note">${escapeHtml(tracking.method)} 本區只是驗證排名品質，不等於實際成交績效。</p></section>`;
  }

  async function load() {
    try {
      const [response, trackingResponse] = await Promise.all([
        fetch("/short-term-decisions?limit=10"),
        fetch("/short-term-ranking/tracking").catch(() => null),
      ]);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "短線排行榜資料無法讀取");
      const tracking = trackingResponse?.ok ? await trackingResponse.json() : null;
      const decisions = data.attention_rankings || data.observation_rankings || data.decisions || [];
      const operationReady = data.operation_ready_candidates || [];
      const attentionRankBySymbol = new Map(decisions.map((item, index) => [String(item.symbol), index + 1]));
      const operationRankings = [...operationReady].sort((left, right) => {
        const statusDifference = (operationPriority[left.operation_status] ?? 99) - (operationPriority[right.operation_status] ?? 99);
        if (statusDifference) return statusDifference;
        const leftRr = Number(left.trade_plan?.cost_adjusted_risk_reward ?? -Infinity);
        const rightRr = Number(right.trade_plan?.cost_adjusted_risk_reward ?? -Infinity);
        if (rightRr !== leftRr) return rightRr - leftRr;
        return (attentionRankBySymbol.get(String(left.symbol)) ?? 99) - (attentionRankBySymbol.get(String(right.symbol)) ?? 99);
      });
      const followUp = data.signal_follow_up || {};
      const newTriggerSymbols = new Set(followUp.available ? (followUp.new_trigger_symbols || []) : operationReady.map(item => String(item.symbol)));
      const newTriggers = operationReady.filter(item => newTriggerSymbols.has(String(item.symbol)));
      const continuedSignals = followUp.continued_signals || [];
      const expiredSignals = followUp.expired_signals || [];
      const fundamentalRejected = data.fundamental_rejections || [];
      const fundamentalPending = data.fundamental_data_pending || [];
      const closest = data.closest_operation_candidates || [];
      const counts = decisions.reduce((result, item) => ({ ...result, [item.candidate_grade]: (result[item.candidate_grade] || 0) + 1 }), {});
      const marketDateNote = data.market_data_aligned ? `大盤資料同日 ${escapeHtml(data.market_data_as_of)}` : `大盤資料日 ${escapeHtml(data.market_data_as_of)} 與訊號日不同，未納入相對分數`;
      const gate = data.publication_gate || {};
      const twseCoverage = gate.markets?.TWSE?.exact_date_coverage_percent;
      const tpexCoverage = gate.markets?.TPEx?.exact_date_coverage_percent;
      const publicationText = data.publication_status === "held_previous"
        ? `今日資料未完整，沿用 ${escapeHtml(data.signal_date)} 的上一份有效榜單`
        : data.publication_status === "unavailable"
          ? "今日資料未完整，且尚無有效舊榜可沿用"
          : "今日榜單已通過同日資料完整性檢查";
      status.innerHTML = `<strong>${publicationText}</strong>｜實際訊號日 ${escapeHtml(data.signal_date)}｜要求日期 ${escapeHtml(data.requested_as_of_date || data.as_of_date)}｜TWSE 同日覆蓋 ${percent(twseCoverage)}｜TPEx 同日覆蓋 ${percent(tpexCoverage)}｜基本面通過 ${number(data.fundamental_gate?.passed)} 檔、阻擋 ${number(data.fundamental_gate?.rejected)} 檔、待同步 ${number(data.fundamental_gate?.data_pending)} 檔｜市場狀態 ${escapeHtml(marketModeText(data.market_mode))}｜${marketDateNote}｜關注前十 A ${counts.A || 0}／B ${counts.B || 0}／C ${counts.C || 0}／D ${counts.D || 0}｜今日新觸發 ${newTriggers.length} 檔｜前次訊號追蹤 ${continuedSignals.length + expiredSignals.length} 檔`;
      rules.innerHTML = `<div><strong>榜單發布完整性</strong><br><span>大盤、TWSE、TPEx 必須同一交易日，兩市場同日行情覆蓋率各至少 95%；未達標時不重排，沿用上一份有效榜單。</span></div><div><strong>資料不一致先暫停</strong><br><span>近四季 EPS 與官方本益比反推獲利差異過大時，先標示待同步，不把它誤判為基本面好或壞。</span></div><div><strong>值得關注與今天可買分開</strong><br><span>A／B／C只比較基本面合格股票的趨勢、相對強度、流動性與法人確認；今天沒有突破，不會因此被說成壞股票。</span></div><div><strong>操作狀態獨立判斷</strong><br><span>突破、量能、ATR與成本後 RR 成立後，仍須通過短線追價控制；5 日急漲且多項乖離過熱時只保留關注，不列為今日可操作。</span></div>`;
      if (!decisions.length) {
        list.innerHTML = data.publication_status === "unavailable"
          ? `<p class="dashboard-empty">${escapeHtml(data.stale_reason)} ${escapeHtml((gate.blocking_reasons || []).join("；"))}</p>`
          : '<p class="dashboard-empty">目前沒有通過基本面、估值、營收、流動性與資料新鮮度門檻的股票。</p>';
        return;
      }
      const operationSection = operationRankings.length
        ? operationRankings.map((item, index) => operationCard(
            item,
            data,
            index + 1,
            attentionRankBySymbol.get(String(item.symbol)),
            newTriggerSymbols.has(String(item.symbol)),
          )).join("")
        : '<p class="dashboard-empty">今天沒有股票同時完成突破、量能、ATR與成本後 RR。這不代表沒有值得關注的股票。</p>';
      const continuedSection = followUp.available
        ? `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">SIGNAL FOLLOW-UP</p><h2>${escapeHtml(followUp.previous_signal_date)} 訊號持續追蹤 ${continuedSignals.length} 檔</h2><p>前一交易日的新進場訊號不會消失；仍符合條件者保留在此。${escapeHtml(followUp.position_notice)}</p></div></div><div class="dashboard-actions">${continuedSignals.length ? continuedSignals.map(item => signalFollowUpCard(item, false, data)).join("") : '<p class="dashboard-empty">前次訊號今天沒有持續符合新進場條件。</p>'}</div></section>`
        : "";
      const expiredSection = followUp.available
        ? `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">SIGNAL CHANGES</p><h2>前次訊號失效或等待重新觸發 ${expiredSignals.length} 檔</h2><p>這裡說明新進場訊號為何失效；若已實際持有，不能直接把本區當成賣出指令。</p></div></div><div class="dashboard-actions">${expiredSignals.length ? expiredSignals.map(item => signalFollowUpCard(item, true, data)).join("") : '<p class="dashboard-empty">前次訊號目前均持續有效。</p>'}</div></section>`
        : "";
      const closestSection = closest.length
        ? closest.map(closestCard).join("")
        : '<p class="dashboard-empty">目前沒有可計算接近度的等待候選。</p>';
      const rejectionSection = fundamentalRejected.length
        ? `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">FUNDAMENTAL BLOCKERS</p><h2>未通過基本面安全門檻</h2><p>這些股票不進入排行榜與今日操作；列出原因是為了讓排除結果可以驗證。</p></div></div><div class="dashboard-actions">${fundamentalRejected.map(fundamentalRejectionCard).join("")}</div></section>`
        : "";
      const pendingSection = fundamentalPending.length
        ? `<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">DATA PENDING</p><h2>財報與估值待同步</h2><p>這些股票暫時不判斷好壞；同步並通過交叉驗證後才重新參與排行榜。</p></div></div><div class="dashboard-actions">${fundamentalPending.map(fundamentalPendingCard).join("")}</div></section>`
        : "";
      list.innerHTML = `<section class="decision-gate"><div><strong>先看可操作排行榜</strong><br><span>只收錄突破、量能、ATR與成本後 RR 已完成者；依 ready、ready_with_risk、成本後 RR 排序。</span></div><div><strong>再看關注排行榜</strong><br><span>關注分數只代表研究優先順序，不代表名次越前越適合買進。</span></div></section><section id="actionableRanking" class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">ACTIONABLE RANKING</p><h2>今日可操作排行榜 ${operationRankings.length} 檔</h2><p>可操作排序不沿用關注名次；今日新觸發 ${newTriggers.length} 檔，其餘為目前仍符合條件的延續訊號。</p></div></div><div class="dashboard-actions">${operationSection}</div></section>${continuedSection}${expiredSection}<section class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">NEAREST SETUPS</p><h2>前十名中最接近可操作的五檔</h2><p>只從下方關注前十名挑選尚待觸發者；先看缺少條件數，再依量能、突破、趨勢、ATR風險與剩餘差距排序。RR不足另列於原股票卡片，不視為接近可操作。</p></div></div><div class="dashboard-actions">${closestSection}</div></section><section id="attentionRanking" class="dashboard-panel"><div class="section-heading compact"><div><p class="eyebrow">ATTENTION TOP 10</p><h2>關注排行榜｜最值得研究的十檔</h2><p>只有基本面安全門檻通過者才能進榜；A／B／C代表關注優先度，不代表今天可以直接買進。</p></div></div><div class="dashboard-actions">${decisions.map(card).join("")}</div></section>${pendingSection}${rejectionSection}${trackingSection(tracking)}`;
    } catch (error) {
      status.textContent = "短線排行榜暫時無法讀取。";
      list.innerHTML = `<p class="dashboard-empty">${escapeHtml(error.message)}</p>`;
    }
  }
  list.addEventListener("click", event => {
    const button = event.target.closest(".record-purchase");
    if (!button) return;
    document.querySelector("#purchaseTitle").textContent = `登記 ${button.dataset.symbol} ${button.dataset.name} 的實際買進`;
    document.querySelector("#purchaseSymbol").value = button.dataset.symbol;
    document.querySelector("#purchaseMarket").value = button.dataset.market;
    document.querySelector("#purchaseSignalDate").value = button.dataset.signalDate;
    document.querySelector("#purchaseStrategyVersion").value = button.dataset.strategyVersion;
    document.querySelector("#entryDate").value = today();
    document.querySelector("#entryPrice").value = button.dataset.entryPrice;
    document.querySelector("#entryShares").value = "1000";
    document.querySelector("#stopPrice").value = button.dataset.stopPrice;
    document.querySelector("#targetPrice").value = button.dataset.targetPrice;
    document.querySelector("#purchaseDialog").showModal();
  });
  positionList.addEventListener("click", event => {
    const button = event.target.closest(".confirm-execution");
    if (!button) return;
    document.querySelector("#executionTitle").textContent = `登記 ${button.dataset.symbol} ${button.dataset.name} 的實際賣出`;
    document.querySelector("#executionPrompt").textContent = button.dataset.reason;
    document.querySelector("#executionSymbol").value = button.dataset.symbol;
    document.querySelector("#executionAction").value = button.dataset.action;
    document.querySelector("#executionReason").value = button.dataset.reason;
    document.querySelector("#executionDate").value = today();
    document.querySelector("#executionPrice").value = button.dataset.price;
    document.querySelector("#executionShares").value = button.dataset.shares;
    document.querySelector("#executionDialog").showModal();
  });
  document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => document.querySelector(`#${button.dataset.closeDialog}`).close()));
  document.querySelector("#purchaseForm").addEventListener("submit", async event => {
    event.preventDefault();
    const payload = {
      symbol: document.querySelector("#purchaseSymbol").value,
      market: document.querySelector("#purchaseMarket").value,
      signal_date: document.querySelector("#purchaseSignalDate").value,
      strategy_version: document.querySelector("#purchaseStrategyVersion").value,
      entry_date: document.querySelector("#entryDate").value,
      entry_price: Number(document.querySelector("#entryPrice").value),
      shares: Number(document.querySelector("#entryShares").value),
      stop_price: Number(document.querySelector("#stopPrice").value),
      target_price: Number(document.querySelector("#targetPrice").value),
    };
    try {
      await positionApi("/short-term-positions", { method: "POST", body: JSON.stringify(payload) });
      document.querySelector("#purchaseDialog").close();
      toast("持倉已儲存，將依每日收盤提供賣出提醒");
      await loadPositions();
    } catch (error) { toast(error.message, true); }
  });
  document.querySelector("#executionForm").addEventListener("submit", async event => {
    event.preventDefault();
    const symbol = document.querySelector("#executionSymbol").value;
    const payload = {
      action: document.querySelector("#executionAction").value,
      execution_date: document.querySelector("#executionDate").value,
      execution_price: Number(document.querySelector("#executionPrice").value),
      shares: Number(document.querySelector("#executionShares").value),
      reason: document.querySelector("#executionReason").value,
    };
    try {
      const result = await positionApi(`/short-term-positions/${encodeURIComponent(symbol)}/executions`, { method: "POST", body: JSON.stringify(payload) });
      document.querySelector("#executionDialog").close();
      toast(result.status === "closed" ? "已登記全數出場" : `已登記減碼，剩餘 ${result.remaining_shares} 股；停損已提高至 ${number(result.active_stop)}`);
      await loadPositions();
    } catch (error) { toast(error.message, true); }
  });
  load();
  loadPositions();
})();
