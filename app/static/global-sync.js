(() => {
  const actions = document.querySelector(".top-actions");
  if (!actions || document.querySelector("#globalSyncButton")) return;
  if (!actions.querySelector('a[href="/performance/"]')) {
    const performanceLink = document.createElement("a");
    performanceLink.href = "/performance/";
    performanceLink.className = `text-link nav-link${location.pathname.startsWith("/performance") ? " active" : ""}`;
    performanceLink.textContent = "模型成績";
    if (location.pathname.startsWith("/performance")) performanceLink.setAttribute("aria-current", "page");
    actions.appendChild(performanceLink);
  }
  const button = document.createElement("button");
  button.id = "globalSyncButton";
  button.type = "button";
  button.className = "global-sync-button";
  button.textContent = "同步所有資料";
  button.title = "更新全市場行情、營收、估值、財報、法人、指數與重大訊息";
  actions.appendChild(button);

  const status = document.createElement("div");
  status.className = "global-sync-progress";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  document.body.appendChild(status);

  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = "同步中…";
    status.className = "global-sync-progress show";
    status.innerHTML = "<strong>正在同步全市場資料</strong><span>行情 → 營收／估值／財報 → 法人 → 市場狀態，約需 30–60 秒。</span>";
    try {
      const response = await fetch("/daily-sync", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `同步失敗（${response.status}）`);
      const steps = result.steps || {};
      const market = steps.market || {};
      const fundamentals = steps.fundamentals || {};
      const institutions = steps.institutions || {};
      const watchlist = steps.watchlist_analysis || {};
      const incomplete = Object.entries(steps).filter(([, value]) => ["failed", "partial"].includes(value?.status)).map(([name]) => name);
      status.className = `global-sync-progress show${incomplete.length ? " warning" : " success"}`;
      status.innerHTML = `<strong>${incomplete.length ? "同步完成，但仍有缺漏" : "所有資料同步完成"}</strong><span>全市場最新資料：上市 ${market.TWSE?.instruments ?? "—"}、上櫃 ${market.TPEx?.instruments ?? "—"}｜營收 ${fundamentals.revenues ?? "—"}｜估值 ${fundamentals.valuations ?? "—"}｜財報 ${fundamentals.financials ?? "—"}｜法人 ${institutions.rows_written ?? "—"}｜我的股票完整資料 ${watchlist.completed ?? 0}/${watchlist.stocks ?? 0}${incomplete.length ? `｜需檢查：${incomplete.join("、")}` : ""}</span>`;
      if (!incomplete.length) setTimeout(() => window.location.reload(), 1800);
    } catch (error) {
      status.className = "global-sync-progress show error";
      status.innerHTML = `<strong>同步失敗</strong><span>${error.message}，現有資料不會被刪除。</span>`;
    } finally {
      button.disabled = false;
      button.textContent = "同步所有資料";
      setTimeout(() => status.classList.remove("show"), 10000);
    }
  });
})();
