(() => {
  const actions = document.querySelector(".top-actions");
  if (!actions || document.querySelector("#globalSyncButton")) return;

  if (!actions.querySelector('a[href="/data-quality/"]')) {
    const qualityLink = document.createElement("a");
    qualityLink.href = "/data-quality/";
    qualityLink.className = "text-link nav-link utility-link";
    qualityLink.textContent = "資料品質";
    if (window.location.pathname === "/data-quality/") {
      qualityLink.classList.add("active");
      qualityLink.setAttribute("aria-current", "page");
    }
    actions.appendChild(qualityLink);
  }

  if (!actions.querySelector('a[href="/dashboard/"]')) {
    const dashboardLink = document.createElement("a");
    dashboardLink.href = "/dashboard/";
    dashboardLink.className = "text-link nav-link";
    dashboardLink.textContent = "今日決策";
    actions.insertBefore(dashboardLink, actions.firstChild);
  }

  const button = document.createElement("button");
  button.id = "globalSyncButton";
  button.type = "button";
  button.className = "global-sync-button";
  button.textContent = "同步所有資料";
  button.title = "更新上市櫃行情、營收、估值、財報、法人資料與觀察股缺失資料";
  actions.appendChild(button);

  const status = document.createElement("div");
  status.className = "global-sync-progress";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  document.body.appendChild(status);

  const labels = {
    market: "行情", fundamentals: "基本面", institutions: "法人", watchlist_analysis: "觀察股",
    research_history_batch: "全市場五年財報", market_context: "市場狀態",
    recommendation_snapshots: "推薦快照", vnext_recommendations: "vNext 推薦", data_freshness: "資料覆蓋率",
  };

  function text(value) { return value == null ? "—" : String(value); }

  function priceCoverage(freshness) {
    return Object.entries(freshness || {}).map(([market, datasets]) => {
      const prices = datasets.prices || {};
      return `${market} 行情 ${text(prices.latest_date)}，覆蓋 ${text(prices.covered_stocks)}/${text(prices.total_stocks)} 檔（${text(prices.coverage_percent)}%）`;
    });
  }

  async function readJson(response) {
    const raw = await response.text();
    try { return raw ? JSON.parse(raw) : {}; }
    catch { throw new Error(`伺服器回傳非預期內容（${response.status}）`); }
  }

  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "同步中⋯";
    status.className = "global-sync-progress show";
    status.innerHTML = "<strong>正在同步所有資料</strong><span>這可能需要一些時間；完成後會顯示每個市場的最新日期與覆蓋率。</span>";
    try {
      const response = await fetch("/daily-sync", { method: "POST" });
      const result = await readJson(response);
      if (!response.ok) throw new Error(result.detail || `同步失敗（${response.status}）`);
      const steps = result.steps || {};
      const incomplete = Object.entries(steps)
        .filter(([, value]) => ["failed", "partial"].includes(value?.status))
        .map(([name]) => labels[name] || name);
      const coverage = priceCoverage(steps.data_freshness?.markets);
      status.className = `global-sync-progress show${incomplete.length ? " warning" : " success"}`;
      status.innerHTML = `<strong>${incomplete.length ? "同步部分完成" : "同步完成"}</strong><span>${coverage.join("；") || "尚未取得覆蓋率資料"}${incomplete.length ? `。需留意：${incomplete.join("、")}` : ""}</span>`;
      if (!incomplete.length) setTimeout(() => window.location.reload(), 2200);
    } catch (error) {
      status.className = "global-sync-progress show error";
      status.innerHTML = `<strong>同步失敗</strong><span>${error.message}</span>`;
    } finally {
      button.disabled = false;
      button.textContent = "同步所有資料";
      setTimeout(() => status.classList.remove("show"), 15000);
    }
  });
})();
