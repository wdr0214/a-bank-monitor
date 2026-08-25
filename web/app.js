const state = {
  rows: [],
  sortKey: "dividend_yield_percentile",
  sortDir: "desc",
  query: "",
  polling: null
};

const GITHUB_WORKFLOW_URL = "https://github.com/wdr0214/a-bank-monitor/actions/workflows/refresh-bank-data.yml";
const GITHUB_PAGES_REFRESH_API = "https://a-bank-monitor.vercel.app/api/refresh";

const fmt = {
  number(value, digits = 2) {
    return Number.isFinite(value) ? value.toFixed(digits) : "--";
  },
  percent(value) {
    return Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "--";
  },
  text(value) {
    return value === null || value === undefined || value === "" ? "--" : String(value);
  }
};

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

async function fetchJson(url) {
  const response = await fetch(`${url}?t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${url} 加载失败：${response.status}`);
  }
  return response.json();
}

async function postRefresh() {
  const endpoint = window.location.hostname.endsWith("github.io")
    ? GITHUB_PAGES_REFRESH_API
    : "/api/refresh";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      signal: controller.signal
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      throw new Error(result.error || `刷新触发失败：${response.status}`);
    }
    return result;
  } finally {
    clearTimeout(timeout);
  }
}

async function loadData() {
  const [latest, status] = await Promise.all([
    fetchJson("data/latest.json"),
    fetchJson("data/status.json")
  ]);
  state.rows = Array.isArray(latest.rows) ? latest.rows : [];
  renderStatus(status, latest);
  renderTable();
  return { latest, status };
}

function timestamp(value) {
  const parsed = Date.parse(String(value || "").replace(" ", "T"));
  return Number.isFinite(parsed) ? parsed : null;
}

function isNewerData(latest, previousGeneratedAt) {
  const current = timestamp(latest.generated_at);
  const previous = timestamp(previousGeneratedAt);
  return current !== null && (previous === null || current > previous);
}

function renderStatus(status, latest) {
  const card = document.getElementById("statusCard");
  const statusText = document.getElementById("statusText");
  const lastSuccess = document.getElementById("lastSuccess");
  const updatedAt = document.getElementById("updatedAt");
  const errorBox = document.getElementById("errorBox");

  const ok = status.ok !== false;
  card.className = `status-card ${ok ? "success" : "failed"}`;
  statusText.textContent = ok ? "正常" : "刷新失败";
  lastSuccess.textContent = status.last_success_at || latest.generated_at || "--";
  updatedAt.textContent = status.generated_at || latest.generated_at || "--";

  const errors = [];
  if (status.error) errors.push(status.error);
  if (Array.isArray(status.errors) && status.errors.length) errors.push(...status.errors);
  if (errors.length) {
    errorBox.textContent = errors.join("\n");
    errorBox.classList.remove("hidden");
  } else {
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
  }
}

function renderTable() {
  const body = document.getElementById("tableBody");
  const rowCount = document.getElementById("rowCount");
  const query = state.query.trim().toLowerCase();
  const filtered = state.rows.filter((row) => {
    if (!query) return true;
    return `${row.code} ${row.name}`.toLowerCase().includes(query);
  });

  const sorted = [...filtered].sort((a, b) => {
    const key = state.sortKey;
    const type = document.querySelector(`th[data-key="${key}"]`)?.dataset.type || "text";
    let av = a[key];
    let bv = b[key];
    if (type === "number") {
      av = toNumber(av);
      bv = toNumber(bv);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return state.sortDir === "asc" ? av - bv : bv - av;
    }
    return state.sortDir === "asc"
      ? String(av || "").localeCompare(String(bv || ""), "zh-Hans-CN")
      : String(bv || "").localeCompare(String(av || ""), "zh-Hans-CN");
  });

  rowCount.textContent = `${sorted.length} 只银行股`;
  body.innerHTML = sorted
    .map((row, index) => {
      const growthClass = Number(row.profit_growth) >= 0 ? "positive" : "negative";
      return `<tr>
        <td>${index + 1}</td>
        <td>${fmt.text(row.code)}</td>
        <td>${fmt.text(row.name)}</td>
        <td>${fmt.number(Number(row.price), 2)}</td>
        <td>${fmt.percent(Number(row.dividend_yield))}</td>
        <td>${fmt.percent(Number(row.annual_dividend_yield))}</td>
        <td>${fmt.percent(Number(row.dividend_yield_percentile))}</td>
        <td class="${growthClass}">${fmt.percent(Number(row.profit_growth))}</td>
        <td>${fmt.text(row.profit_period)}</td>
        <td>${fmt.number(Number(row.dividend_dps_used), 4)}</td>
        <td>${fmt.number(Number(row.annual_eps), 4)}</td>
        <td>${fmt.percent(Number(row.dividend_payout_ratio))}</td>
        <td>${fmt.number(Number(row.annual_dividend), 4)}</td>
        <td>${fmt.number(Number(row.ttm_dividend), 4)}</td>
        <td>${fmt.text(row.dividend_basis)}</td>
        <td class="${row.error ? "negative" : "empty"}">${fmt.text(row.error)}</td>
      </tr>`;
    })
    .join("");
}

function wireSorting() {
  document.querySelectorAll("th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = th.dataset.type === "number" ? "desc" : "asc";
      }
      renderTable();
    });
  });
}

async function triggerRefresh() {
  const button = document.getElementById("refreshBtn");
  const errorBox = document.getElementById("errorBox");
  const previousGeneratedAt = document.getElementById("updatedAt").textContent;
  button.disabled = true;
  button.textContent = "正在提交";
  try {
    const result = await postRefresh();
    errorBox.textContent = result.message || "刷新任务已提交，正在等待数据更新。";
    errorBox.classList.remove("hidden");
    if (state.polling) clearInterval(state.polling);
    button.textContent = "正在刷新";
    let refreshComplete = false;

    const poll = async () => {
      try {
        const { latest, status } = await loadData();
        if (isNewerData(latest, previousGeneratedAt)) {
          clearInterval(state.polling);
          state.polling = null;
          refreshComplete = true;
          button.disabled = false;
          button.textContent = "手动刷新";
          errorBox.textContent = `数据已更新至 ${latest.generated_at || status.generated_at}`;
          errorBox.classList.remove("hidden");
        }
      } catch (error) {
        // A deployment can briefly return an old or unavailable static file. Keep polling.
        errorBox.textContent = `正在等待最新数据发布：${error.message || error}`;
        errorBox.classList.remove("hidden");
      }
    };

    await poll();
    if (!refreshComplete) {
      state.polling = setInterval(poll, 10000);
    }
    setTimeout(() => {
      if (refreshComplete || !state.polling) return;
      clearInterval(state.polling);
      state.polling = null;
      button.disabled = false;
      button.textContent = "手动刷新";
      errorBox.textContent = "刷新任务尚未在 12 分钟内发布新数据。请稍后再次点击，或在 GitHub Actions 中查看任务状态。";
      errorBox.classList.remove("hidden");
    }, 12 * 60 * 1000);
  } catch (error) {
    if (window.location.hostname.endsWith("github.io")) {
      window.open(GITHUB_WORKFLOW_URL, "_blank", "noopener");
      errorBox.textContent = `无法自动触发刷新：${error.message || error}\n已打开 GitHub Actions 页面；登录 GitHub 后点击 Run workflow 可手动刷新计算。`;
    } else {
      errorBox.textContent = error.message || String(error);
    }
    errorBox.classList.remove("hidden");
    button.disabled = false;
    button.textContent = "手动刷新";
  }
}

document.getElementById("searchInput").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderTable();
});
document.getElementById("refreshBtn").addEventListener("click", triggerRefresh);
wireSorting();
loadData().catch((error) => {
  document.getElementById("statusText").textContent = "加载失败";
  document.getElementById("errorBox").textContent = error.message || String(error);
  document.getElementById("errorBox").classList.remove("hidden");
});
