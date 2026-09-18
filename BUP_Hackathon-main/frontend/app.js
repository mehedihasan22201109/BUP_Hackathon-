// GridWise frontend � talks to the FastAPI server in /app.
// API base URL is resolved dynamically: same-origin if served by FastAPI,
// otherwise http://127.0.0.1:8000.
const API_BASE = "http://127.0.0.1:8000";

const $ = (id) => document.getElementById(id);

const SAMPLES_URL = "samples.json"; // works when served from /frontend/
let SAMPLES = [];   // cached sample cases
let chart = null;   // Chart.js instance

// --------------------------------------------------------------------------- //
// Bootstrap                                                                    //
// --------------------------------------------------------------------------- //
window.addEventListener("DOMContentLoaded", async () => {
  buildHoursTable();
  await loadSamples();
  wireEvents();
  checkHealth();
  setInterval(checkHealth, 15000);
});

// --------------------------------------------------------------------------- //
// Health                                                                       //
// --------------------------------------------------------------------------- //
async function checkHealth() {
  const dot = $("status-dot");
  const txt = $("status-text");
  try {
    const r = await fetch(API_BASE + "/health", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    dot.className = "dot ok";
    txt.textContent = `API ${j.service} � v${j.version}`;
  } catch (e) {
    dot.className = "dot bad";
    txt.textContent = "API unreachable � start uvicorn on :8000";
  }
}

// --------------------------------------------------------------------------- //
// Sample loader                                                                //
// --------------------------------------------------------------------------- //
async function loadSamples() {
  try {
    const r = await fetch(SAMPLES_URL);
    if (!r.ok) throw new Error("samples " + r.status);
    const j = await r.json();
    SAMPLES = j.cases || [];
    const sel = $("sample-picker");
    SAMPLES.forEach((c) => {
      const o = document.createElement("option");
      o.value = c.id;
      o.textContent = `${c.id} � ${(c.input.operator_notes || []).length} note(s)`;
      sel.appendChild(o);
    });
    if (SAMPLES.length) loadSample(SAMPLES[0].id);
  } catch (e) {
    console.warn("Could not load samples:", e);
    // Fall back to a single placeholder scenario so the form is still usable.
    seedEmptyScenario();
  }
}

function seedEmptyScenario() {
  const hours = Array.from({ length: 24 }, (_, h) => ({
    hour: h, demand_kwh: 100, solar_kwh: 0, tariff_bdt_per_kwh: 10,
  }));
  window.__seed = { id: "CUSTOM-01", battery: { capacity_kwh: 100, initial_energy_kwh: 50, minimum_energy_kwh: 10, max_charge_kwh_per_hour: 30, max_discharge_kwh_per_hour: 30 }, hours, operator_notes: [] };
  applyScenario(window.__seed);
}

function loadSample(id) {
  const c = SAMPLES.find((x) => x.id === id);
  if (!c) return;
  applyScenario(c.input);
  $("f-scenario_id").value = c.id;
  $("sample-picker").value = c.id;
}

function applyScenario(input) {
  const b = input.battery;
  $("b-capacity").value = b.capacity_kwh;
  $("b-initial").value  = b.initial_energy_kwh;
  $("b-min").value      = b.minimum_energy_kwh;
  $("b-mch").value      = b.max_charge_kwh_per_hour;
  $("b-mdis").value     = b.max_discharge_kwh_per_hour;
  const tb = document.querySelector("#hours-table tbody");
  tb.innerHTML = "";
  (input.hours || []).forEach((row, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.hour ?? idx}</td>
      <td><input data-k="demand_kwh" type="number" step="0.1" min="0" value="${row.demand_kwh}"></td>
      <td><input data-k="solar_kwh"  type="number" step="0.1" min="0" value="${row.solar_kwh}"></td>
      <td><input data-k="tariff_bdt_per_kwh" type="number" step="0.01" min="0" value="${row.tariff_bdt_per_kwh}"></td>`;
    tb.appendChild(tr);
  });
  $("f-notes").value = (input.operator_notes || []).join("\n");
}

function buildHoursTable() {
  const tb = document.querySelector("#hours-table tbody");
  tb.innerHTML = "";
  for (let h = 0; h < 24; h++) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${h}</td>
      <td><input data-k="demand_kwh" type="number" step="0.1" min="0" value="100"></td>
      <td><input data-k="solar_kwh"  type="number" step="0.1" min="0" value="0"></td>
      <td><input data-k="tariff_bdt_per_kwh" type="number" step="0.01" min="0" value="10"></td>`;
    tb.appendChild(tr);
  }
}

// --------------------------------------------------------------------------- //
// Wire UI events                                                               //
// --------------------------------------------------------------------------- //
function wireEvents() {
  $("sample-picker").addEventListener("change", (e) => {
    if (e.target.value) loadSample(e.target.value);
  });
  $("btn-load").addEventListener("click", () => {
    const id = $("sample-picker").value;
    if (id) loadSample(id);
  });
  $("btn-clear").addEventListener("click", () => { $("f-notes").value = ""; });
  $("btn-optimize").addEventListener("click", runOptimize);
}

function readForm() {
  const hours = Array.from(document.querySelectorAll("#hours-table tbody tr")).map((tr) => ({
    hour: Number(tr.children[0].textContent),
    demand_kwh: Number(tr.querySelector('[data-k="demand_kwh"]').value),
    solar_kwh:  Number(tr.querySelector('[data-k="solar_kwh"]').value),
    tariff_bdt_per_kwh: Number(tr.querySelector('[data-k="tariff_bdt_per_kwh"]').value),
  }));
  const battery = {
    capacity_kwh: Number($("b-capacity").value),
    initial_energy_kwh: Number($("b-initial").value),
    minimum_energy_kwh: Number($("b-min").value),
    max_charge_kwh_per_hour: Number($("b-mch").value),
    max_discharge_kwh_per_hour: Number($("b-mdis").value),
  };
  const operator_notes = $("f-notes").value
    .split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  return {
    scenario_id: $("f-scenario_id").value.trim() || "SCENARIO",
    operator_notes, battery, hours,
  };
}

// --------------------------------------------------------------------------- //
// Optimize                                                                     //
// --------------------------------------------------------------------------- //
async function runOptimize() {
  const btn = $("btn-optimize");
  btn.disabled = true;
  const oldText = btn.textContent;
  btn.textContent = "Optimizing�";
  clearError();
  try {
    const body = readForm();
    const r = await fetch(API_BASE + "/optimize-energy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`HTTP ${r.status}\n${txt}`);
    }
    const resp = await r.json();
    render(resp);
  } catch (e) {
    showError(String(e.message || e));
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

function showError(msg) {
  let bar = $("errorbar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "errorbar";
    bar.className = "errorbar";
    $("panel-results").prepend(bar);
  }
  bar.textContent = msg;
}
function clearError() {
  const bar = $("errorbar");
  if (bar) bar.remove();
}

// --------------------------------------------------------------------------- //
// Render                                                                       //
// --------------------------------------------------------------------------- //
function render(resp) {
  // KPIs
  $("kpi-grid").textContent = fmt(resp.total_grid_kwh);
  $("kpi-cost").textContent = fmt(resp.total_cost_bdt);
  $("kpi-peak").textContent = fmt(resp.peak_grid_kwh);
  $("kpi-directives").textContent =
    `${(resp.directive_interpretation || []).filter((d) => d.applies).length} / ${(resp.directive_interpretation || []).length}`;

  $("plan-summary").textContent = resp.plan_summary || "(no summary returned)";

  // Directive cards
  const wrap = $("directives");
  wrap.innerHTML = "";
  for (const d of resp.directive_interpretation || []) {
    const div = document.createElement("div");
    div.className = "dir " + (d.applies ? "applies" : "skip");
    const sa = d.structured_adjustment
      ? Object.entries(d.structured_adjustment)
          .filter(([, v]) => v !== null && v !== undefined && v !== "")
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(",") : v}`)
          .join(" � ")
      : "";
    div.innerHTML = `
      <div class="head">
        <span>Note ${d.note_index}</span>
        <span class="pill">${d.directive_type}</span>
        <span class="pill">${d.applies ? "applied" : "no-op"}</span>
      </div>
      <div class="why">${escapeHtml(d.explanation || "")}</div>
      ${sa ? `<div class="why">${escapeHtml(sa)}</div>` : ""}
    `;
    wrap.appendChild(div);
  }

  // Plan table
  const tb = document.querySelector("#plan-table tbody");
  tb.innerHTML = "";
  for (const r of resp.hourly_plan || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.hour}</td>
      <td>${fmt(r.grid_kwh)}</td>
      <td>${fmt(r.solar_used_kwh)}</td>
      <td>${r.battery_action}</td>
      <td>${fmt(r.battery_kwh)}</td>
      <td>${fmt(r.battery_energy_after_kwh)}</td>`;
    tb.appendChild(tr);
  }

  drawChart(resp);
}

function drawChart(resp) {
  const labels = resp.hourly_plan.map((r) => r.hour);
  const grid   = resp.hourly_plan.map((r) => r.grid_kwh);
  const solar  = resp.hourly_plan.map((r) => r.solar_used_kwh);
  const batt   = resp.hourly_plan.map((r) =>
    r.battery_action === "charge" ? r.battery_kwh
    : r.battery_action === "discharge" ? -r.battery_kwh
    : 0);
  const soc    = resp.hourly_plan.map((r) => r.battery_energy_after_kwh);

  const ctx = document.getElementById("planChart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { type: "bar",  label: "Grid kWh",     data: grid,  backgroundColor: "rgba(249,115,22,0.85)",  stack: "energy" },
        { type: "bar",  label: "Solar used",   data: solar, backgroundColor: "rgba(250,204,21,0.85)", stack: "energy" },
        { type: "bar",  label: "Battery �",    data: batt,  backgroundColor: "rgba(56,189,248,0.85)", stack: "energy" },
        { type: "line", label: "SOC (kWh)",    data: soc,   borderColor: "rgba(167,139,250,1)", backgroundColor: "rgba(167,139,250,0.15)", yAxisID: "y2", tension: 0.3, pointRadius: 2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: "#0f172a", titleColor: "#f8fafc", bodyColor: "#f8fafc", borderColor: "#0f172a", borderWidth: 1 } },
      scales: {
        x:  { stacked: true, title: { display: true, text: "hour",     color: "#475569" }, ticks: { color: "#475569" }, grid: { color: "#e2e8f0" } },
        y:  { stacked: true, title: { display: true, text: "kWh / h",  color: "#475569" }, ticks: { color: "#475569" }, grid: { color: "#e2e8f0" } },
        y2: { position: "right", title: { display: true, text: "SOC (kWh)", color: "#475569" }, ticks: { color: "#475569" }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

function fmt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "�";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "\u0027": "&#39;" }[c]));
}
