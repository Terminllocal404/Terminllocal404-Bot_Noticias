const API_BASE = window.API_BASE || "http://127.0.0.1:8000";

const newsList = document.getElementById("newsList");
const cveList = document.getElementById("cveList");
const alertList = document.getElementById("alertList");
const searchInput = document.getElementById("searchInput");
const categoryFilter = document.getElementById("categoryFilter");
const severityFilter = document.getElementById("severityFilter");
const refreshBtn = document.getElementById("refreshBtn");

function severityClass(level) {
  const v = (level || "").toLowerCase();
  if (v === "critical") return "critical";
  if (v === "high") return "high";
  if (v === "medium") return "medium";
  return "";
}

function renderCard(item, isCve = false) {
  const card = document.createElement("article");
  card.className = `card ${severityClass(item.severity)}`;
  const title = isCve ? item.cve_id : item.title;
  const link = isCve ? "" : (item.link || "");
  card.innerHTML = `
    <h3>${title || "Untitled"}</h3>
    <div class="meta">${item.source || "CVE Feed"} | ${item.category || "security"} | ${item.severity || "MEDIUM"}</div>
    <p>${item.summary || "No summary available."}</p>
    ${link ? `<a href="${link}" target="_blank" rel="noopener noreferrer">Read more</a>` : ""}
  `;
  return card;
}

async function fetchJson(path, params = {}) {
  const url = new URL(`${API_BASE}${path}`);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
  });
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

async function loadNews() {
  const category = categoryFilter.value;
  const search = searchInput.value.trim();
  const severity = severityFilter.value;
  const endpoint = category ? `/news/${category}` : "/news";
  const data = await fetchJson(endpoint, { search, severity, limit: 50 });
  newsList.innerHTML = "";
  data.items.forEach(item => newsList.appendChild(renderCard(item)));
}

async function loadCves() {
  const severity = severityFilter.value;
  const data = await fetchJson("/cves", { severity, limit: 50 });
  cveList.innerHTML = "";
  data.items.forEach(item => cveList.appendChild(renderCard(item, true)));
}

async function loadAlerts() {
  const data = await fetchJson("/alerts", { limit: 50 });
  alertList.innerHTML = "";
  data.items.forEach(item => alertList.appendChild(renderCard(item)));
}

async function refreshAll() {
  await Promise.all([loadNews(), loadCves(), loadAlerts()]);
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

[searchInput, categoryFilter, severityFilter].forEach(el => {
  el.addEventListener("input", refreshAll);
  el.addEventListener("change", refreshAll);
});
refreshBtn.addEventListener("click", refreshAll);

refreshAll();
setInterval(refreshAll, 60000);
