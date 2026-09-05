const state = {
  period: "7d",
  from: "",
  to: "",
  project: "",
  provider: "",
  q: "",
  limit: 20,
  offset: 0,
};
let currentTaskId = "";

const fmt = new Intl.NumberFormat("zh-CN");

function $(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function apiQuery(extra = {}) {
  const params = new URLSearchParams({
    period: state.period,
    from: state.from,
    to: state.to,
    project: state.project,
    provider: state.provider,
    ...extra,
  });
  return params.toString();
}

function formatTime(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
}

function formatMoney(value, partial = false) {
  if (value == null) return "未配置";
  return `¥${Number(value).toFixed(4)}${partial ? "*" : ""}`;
}

function formatDate(day) {
  if (!day) return "-";
  const parts = day.split("-");
  if (parts.length === 3) return `${parts[1]}-${parts[2]}`;
  return day;
}

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function renderCards(summary) {
  const cards = [
    { label: "总Token", value: fmt.format(summary.total_tokens), sub: `${fmt.format(summary.task_count)} 个任务` },
    { label: "输入", value: fmt.format(summary.input_tokens), sub: `缓存 ${fmt.format(summary.cached_input_tokens)}` },
    { label: "输出", value: fmt.format(summary.output_tokens), sub: `${fmt.format(summary.turn_count)} 轮` },
    { label: "思考输出", value: fmt.format(summary.reasoning_output_tokens), sub: `缓存写入 ${fmt.format(summary.cache_write_input_tokens)}` },
    {
      label: "总费用",
      value: formatMoney(summary.cost_cny, (summary.unpriced_task_count || 0) > 0),
      sub: summary.unpriced_task_count ? `${summary.unpriced_task_count} 个任务未配置价格` : "按模型价格计算",
    },
  ];
  $("cards").innerHTML = cards
    .map(
      (card) => `
        <div class="card">
          <div class="label">${card.label}</div>
          <div class="value">${card.value}</div>
          <div class="sub">${card.sub}</div>
        </div>`
    )
    .join("");
}

function renderTrend(trend) {
  const el = $("trend");
  if (!trend || trend.length === 0) {
    el.innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }
  const max = Math.max(...trend.map((item) => item.total_tokens), 1);
  el.innerHTML = trend
    .map((item) => {
      const height = Math.max(2, Math.round((item.total_tokens / max) * 100));
      return `
        <div class="bar-col">
          <div class="bar-track">
            <div class="bar" style="height:${height}%">
              <span>${fmt.format(item.total_tokens)}</span>
            </div>
          </div>
          <div class="bar-label" title="${item.group_key}">${formatDate(item.group_key)}</div>
        </div>`;
    })
    .join("");
}

function renderBreakdown(el, rows, valueKey = "total_tokens", nameKey = "display_name") {
  if (!rows || rows.length === 0) {
    el.innerHTML = '<div class="empty">暂无数据</div>';
    return;
  }
  const max = Math.max(...rows.map((row) => row[valueKey]), 1);
  el.innerHTML = rows
    .map((row) => {
      const width = Math.max(2, Math.round((row[valueKey] / max) * 100));
      const name = row[nameKey] || row.group_name || "未知";
      return `
        <div class="break-row">
          <div class="break-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          <div class="break-bar"><div class="break-fill" style="width:${width}%"></div></div>
          <div class="break-value">${fmt.format(row[valueKey])}</div>
        </div>`;
    })
    .join("");
}

function renderProjects(rows) {
  const body = $("projectsBody");
  if (!rows || rows.length === 0) {
    body.innerHTML = '<tr><td colspan="5" class="empty">暂无数据</td></tr>';
    return;
  }
  const total = rows.reduce(
    (acc, row) => {
      acc.task_count += row.task_count || 0;
      acc.turn_count += row.turn_count || 0;
      acc.total_tokens += row.total_tokens || 0;
      acc.cost_cny += row.cost_cny || 0;
      acc.unpriced_task_count += row.unpriced_task_count || 0;
      return acc;
    },
    { task_count: 0, turn_count: 0, total_tokens: 0, cost_cny: 0, unpriced_task_count: 0 }
  );
  body.innerHTML = `
      <tr class="total-row">
        <td>合计</td>
        <td>${total.task_count}</td>
        <td>${total.turn_count}</td>
        <td>${fmt.format(total.total_tokens)}</td>
        <td title="${total.unpriced_task_count ? "含未配置价格任务" : ""}">${formatMoney(total.cost_cny, total.unpriced_task_count > 0)}</td>
      </tr>` +
    rows
      .map(
        (row) => `
          <tr>
            <td title="${escapeHtml(row.group_name)}">${escapeHtml(row.group_name)}</td>
            <td>${row.task_count}</td>
            <td>${row.turn_count}</td>
            <td>${fmt.format(row.total_tokens)}</td>
            <td title="${row.unpriced_task_count ? "含未配置价格任务" : ""}">${formatMoney(row.cost_cny, row.unpriced_task_count > 0)}</td>
          </tr>`
      )
      .join("");
}

function renderTasks(items) {
  const body = $("tasksBody");
  if (!items || items.length === 0) {
    body.innerHTML = '<tr><td colspan="7" class="empty">暂无数据</td></tr>';
    return;
  }
  body.innerHTML = items
    .map(
      (item) => `
        <tr class="task-row" data-id="${item.id}">
          <td><div class="task-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title || "未命名任务")}</div></td>
          <td>${escapeHtml(item.project_name || "未知")}</td>
          <td>${escapeHtml(item.provider || "-")}</td>
          <td>${escapeHtml(item.model || "-")}</td>
          <td>${item.turn_count}</td>
          <td>${fmt.format(item.total_tokens)}</td>
          <td>${formatMoney(item.cost_cny)}</td>
        </tr>`
    )
    .join("");
}

function renderFilters(data) {
  const projectSelect = $("projectFilter");
  const providerSelect = $("providerFilter");
  projectSelect.innerHTML =
    '<option value="">全部项目</option>' +
    data.projects
      .map((p) => `<option value="${escapeHtml(p.key)}">${escapeHtml(p.name)}</option>`)
      .join("");
  providerSelect.innerHTML =
    '<option value="">全部供应商</option>' +
    data.providers
      .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
      .join("");
  projectSelect.value = state.project;
  providerSelect.value = state.provider;
}

async function loadSummary() {
  const data = await fetchJSON(`/api/summary?${apiQuery()}`);
  renderCards(data.summary);
  renderTrend(data.trend);
  renderBreakdown($("providers"), data.providers);
  renderBreakdown($("models"), data.models, "total_tokens", "group_name");
  renderProjects(data.projects);
}

async function loadTasks() {
  const data = await fetchJSON(`/api/tasks?${apiQuery({ limit: state.limit, offset: state.offset, q: state.q })}`);
  renderTasks(data.items);
  const pages = Math.max(1, Math.ceil(data.total / state.limit));
  const current = Math.floor(state.offset / state.limit) + 1;
  $("pageInfo").textContent = `第 ${current} / ${pages} 页，共 ${data.total} 个任务`;
  $("prevBtn").disabled = state.offset <= 0;
  $("nextBtn").disabled = current >= pages;
}

async function openTask(id) {
  try {
    currentTaskId = id;
    const data = await fetchJSON(`/api/tasks/${id}/turns`);
    const task = data.task;
    $("modalTitle").textContent = task.title || "未命名任务";
    $("projectInput").value = task.project_name || "";
    $("modalMeta").textContent = [
      `项目: ${task.project_name || "未知"}`,
      `供应商: ${task.provider || "-"}`,
      `模型: ${task.model || "-"}`,
      `创建: ${formatTime(task.created_at)}`,
      `总Token: ${fmt.format(task.total_tokens)}`,
      `费用: ${formatMoney(task.cost_cny)}`,
    ].join("  |  ");
    const body = $("turnsBody");
    if (!data.turns.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty">暂无轮次明细</td></tr>';
    } else {
    const sums = data.turns.reduce(
      (acc, turn) => {
        acc.input_tokens += turn.input_tokens || 0;
        acc.cached_input_tokens += turn.cached_input_tokens || 0;
        acc.output_tokens += turn.output_tokens || 0;
        acc.reasoning_output_tokens += turn.reasoning_output_tokens || 0;
        acc.total_tokens += turn.total_tokens || 0;
        acc.cost_cny += turn.cost_cny || 0;
        return acc;
      },
      {
        input_tokens: 0,
        cached_input_tokens: 0,
        output_tokens: 0,
        reasoning_output_tokens: 0,
        total_tokens: 0,
        cost_cny: 0,
      }
    );
    body.innerHTML =
      `
        <tr class="total-row">
          <td>合计</td>
          <td>-</td>
          <td>${fmt.format(sums.input_tokens)}</td>
          <td>${fmt.format(sums.cached_input_tokens)}</td>
          <td>${fmt.format(sums.output_tokens)}</td>
          <td>${fmt.format(sums.reasoning_output_tokens)}</td>
          <td>${fmt.format(sums.total_tokens)}</td>
          <td>${formatMoney(sums.cost_cny)}</td>
        </tr>` +
      data.turns
        .map(
          (turn) => `
            <tr>
              <td>${turn.turn_index + 1}</td>
              <td>${formatTime(turn.ts)}</td>
              <td>${fmt.format(turn.input_tokens)}</td>
              <td>${fmt.format(turn.cached_input_tokens)}</td>
              <td>${fmt.format(turn.output_tokens)}</td>
              <td>${fmt.format(turn.reasoning_output_tokens)}</td>
              <td>${fmt.format(turn.total_tokens)}</td>
              <td>${formatMoney(turn.cost_cny)}</td>
            </tr>`
        )
        .join("");
  }
    $("modal").classList.remove("hidden");
  } catch (err) {
    $("modalTitle").textContent = "加载失败";
    $("modalMeta").textContent = String(err);
    $("turnsBody").innerHTML = "";
    $("modal").classList.remove("hidden");
  }
}

async function saveProject() {
  if (!currentTaskId) return;
  const name = $("projectInput").value.trim();
  $("saveProject").disabled = true;
  try {
    const response = await fetch(`/api/tasks/${currentTaskId}/project`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: name }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    $("modalMeta").textContent = [
      `项目: ${data.task.project_name || "未知"}`,
      `供应商: ${data.task.provider || "-"}`,
      `模型: ${data.task.model || "-"}`,
      `创建: ${formatTime(data.task.created_at)}`,
      `总Token: ${fmt.format(data.task.total_tokens)}`,
      `费用: ${formatMoney(data.task.cost_cny)}`,
    ].join("  |  ");
    loadSummary();
    loadTasks();
  } catch (err) {
    $("modalMeta").textContent = "保存失败: " + String(err);
  } finally {
    $("saveProject").disabled = false;
  }
}

async function resetProject() {
  if (!currentTaskId) return;
  $("projectInput").value = "";
  await saveProject();
}

async function refreshData() {
  $("refreshBtn").disabled = true;
  try {
    await fetch("/api/refresh", { method: "POST" });
    await Promise.all([loadSummary(), loadTasks()]);
  } finally {
    $("refreshBtn").disabled = false;
  }
}

function setPeriod(period) {
  state.period = period;
  state.from = "";
  state.to = "";
  state.offset = 0;
  document.querySelectorAll(".period-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.period === period);
  });
  loadSummary();
  loadTasks();
}

function applyCustom() {
  state.from = $("fromDate").value;
  state.to = $("toDate").value;
  if (!state.from && !state.to) return;
  state.period = "custom";
  state.offset = 0;
  document.querySelectorAll(".period-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.period === state.period);
  });
  loadSummary();
  loadTasks();
}

function init() {
  document.querySelectorAll(".period-btn").forEach((btn) => {
    btn.addEventListener("click", () => setPeriod(btn.dataset.period));
  });
  $("applyCustom").addEventListener("click", applyCustom);
  $("refreshBtn").addEventListener("click", refreshData);
  $("closeModal").addEventListener("click", () => $("modal").classList.add("hidden"));
  $("saveProject").addEventListener("click", saveProject);
  $("resetProject").addEventListener("click", resetProject);
  $("modal").addEventListener("click", (event) => {
    if (event.target === $("modal")) $("modal").classList.add("hidden");
  });
  $("tasksBody").addEventListener("click", (event) => {
    const row = event.target.closest(".task-row");
    if (row && row.dataset.id) openTask(row.dataset.id);
  });
  $("projectFilter").addEventListener("change", (event) => {
    state.project = event.target.value;
    state.offset = 0;
    loadSummary();
    loadTasks();
  });
  $("providerFilter").addEventListener("change", (event) => {
    state.provider = event.target.value;
    state.offset = 0;
    loadSummary();
    loadTasks();
  });
  $("searchInput").addEventListener("change", (event) => {
    state.q = event.target.value.trim();
    state.offset = 0;
    loadTasks();
  });
  $("prevBtn").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadTasks();
  });
  $("nextBtn").addEventListener("click", () => {
    state.offset += state.limit;
    loadTasks();
  });

  fetchJSON(`/api/filters`).then(renderFilters);
  loadSummary();
  loadTasks();
}

init();
