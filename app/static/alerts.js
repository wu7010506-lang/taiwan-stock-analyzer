const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const READ_KEY = "tw-stock-alerts-read";
let alerts = [];
let severity = "all";

async function api(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `伺服器錯誤（${response.status}）`);
  return data;
}

function readAlerts() {
  try { return new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]")); }
  catch { return new Set(); }
}

function alertId(item) { return `${item.symbol}|${item.category}|${item.title}|${item.as_of || ""}`; }

function saveRead(ids) { localStorage.setItem(READ_KEY, JSON.stringify([...ids])); }

function filteredAlerts() {
  const category = $("#alertCategory").value;
  const keyword = $("#alertSearch").value.trim().toLowerCase();
  const unreadOnly = $("#unreadOnly").checked;
  const read = readAlerts();
  return alerts.filter(item => {
    if (severity !== "all" && item.severity !== severity) return false;
    if (category && item.category !== category) return false;
    if (unreadOnly && read.has(alertId(item))) return false;
    return !keyword || `${item.symbol} ${item.name} ${item.title} ${item.message}`.toLowerCase().includes(keyword);
  });
}

function renderAlerts() {
  const rows = filteredAlerts();
  const read = readAlerts();
  $("#alertStatus").textContent = `顯示 ${rows.length} 則，共 ${alerts.length} 則提醒`;
  $("#alertEmpty").classList.toggle("hidden", rows.length > 0);
  $("#alertEmptyTitle").textContent = alerts.length ? "沒有符合篩選條件的提醒" : "目前沒有觸發提醒";
  $("#alertGrid").innerHTML = rows.map(item => {
    const id = alertId(item);
    const isRead = read.has(id);
    return `<article class="alert-card ${item.severity}${isRead ? " is-read" : ""}" data-symbol="${item.symbol}" data-alert-id="${encodeURIComponent(id)}" tabindex="0" role="link">
      <div class="alert-card-head"><span>${item.category}</span><small>${item.as_of || "資料日期不明"}</small></div>
      <h2>${item.symbol} ${item.name}</h2><h3>${item.title}</h3><p>${item.message}</p>
      <div class="alert-card-actions"><span>${isRead ? "已讀" : "新提醒"}</span><button type="button" class="mark-read">${isRead ? "標示未讀" : "標示已讀"}</button><strong>查看個股 →</strong></div>
    </article>`;
  }).join("");
  $$("#alertGrid .alert-card").forEach(card => {
    const open = () => location.href = `/?symbol=${encodeURIComponent(card.dataset.symbol)}`;
    card.addEventListener("click", open);
    card.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
    card.querySelector(".mark-read").addEventListener("click", event => {
      event.stopPropagation();
      const ids = readAlerts();
      const id = decodeURIComponent(card.dataset.alertId);
      ids.has(id) ? ids.delete(id) : ids.add(id);
      saveRead(ids);
      renderAlerts();
    });
  });
}

function renderSummary(data) {
  $("#alertSummary").innerHTML = `<div><span>監控股票</span><strong>${data.stocks_monitored}</strong></div><div class="warning"><span>風險注意</span><strong>${data.counts.warning}</strong></div><div class="opportunity"><span>研究機會</span><strong>${data.counts.opportunity}</strong></div><div><span>事件資訊</span><strong>${data.counts.info}</strong></div>`;
  const categories = [...new Set(alerts.map(item => item.category))].sort();
  $("#alertCategory").innerHTML = `<option value="">全部類別</option>${categories.map(value => `<option value="${value}">${value}</option>`).join("")}`;
}

async function loadAlerts() {
  const button = $("#reloadAlertsButton");
  button.disabled = true; button.textContent = "檢查中…";
  try {
    const data = await api("/alerts");
    alerts = data.alerts;
    renderSummary(data);
    renderAlerts();
  } catch (error) { $("#alertStatus").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "重新檢查"; }
}

async function checkHealth() {
  const el = $("#apiStatus");
  try { await api("/health"); el.className = "status-dot online"; el.innerHTML = "<i></i>服務正常"; }
  catch { el.className = "status-dot offline"; el.innerHTML = "<i></i>服務中斷"; }
}

$$('.alert-filter-chip').forEach(button => button.addEventListener("click", () => {
  severity = button.dataset.severity;
  $$('.alert-filter-chip').forEach(item => item.classList.toggle("active", item === button));
  renderAlerts();
}));
$("#alertCategory").addEventListener("change", renderAlerts);
$("#alertSearch").addEventListener("input", renderAlerts);
$("#unreadOnly").addEventListener("change", renderAlerts);
$("#markAllRead").addEventListener("click", () => { saveRead(new Set(alerts.map(alertId))); renderAlerts(); });
$("#reloadAlertsButton").addEventListener("click", loadAlerts);
checkHealth(); loadAlerts();
