const labels = {
  terms: "Terms",
  courses: "Courses",
  instructors: "Instructors",
  rooms: "Rooms",
  groups: "Student groups",
  timeslots: "Timeslots",
  classes: "Classes",
};
const resourceFields = {
  terms: ["name", "start_date", "end_date", "active"],
  courses: ["term_id", "code", "name"],
  instructors: ["name", "email"],
  rooms: ["name", "building", "capacity"],
  groups: ["name", "size"],
  timeslots: ["term_id", "label", "days", "start", "length", "weeks"],
  classes: [
    "term_id", "course_id", "name", "instructor_id", "room_required",
    "expected_enrollment", "duration", "allowed_room_ids",
    "allowed_timeslot_ids", "preferred_timeslot_ids", "preferred_room_ids",
    "active", "group_ids",
  ],
};
const integerFields = new Set([
  "term_id", "course_id", "instructor_id", "capacity", "size", "start",
  "length", "expected_enrollment", "duration",
]);
const booleanFields = new Set(["active", "room_required"]);
const terminalStatuses = new Set([
  "complete", "partial", "infeasible_proven", "timeout_unknown",
  "unsupported", "error", "cancelled", "invalid_solution",
]);
const state = { resource: "terms", editingId: null, jobId: null, classNames: {} };
const $ = (selector) => document.querySelector(selector);

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body && typeof body === "object" ? body.detail : body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 3200);
}

function setCallout(selector, message, isError = false) {
  const element = $(selector);
  element.textContent = message;
  element.classList.remove("hidden", "error");
  if (isError) element.classList.add("error");
}

function statusBadge(status) {
  return `<span class="status ${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function loadHealth() {
  try {
    const health = await request("/api/health");
    $("#api-status").textContent = `API ${health.status} · SQLite`;
    $("#api-status").classList.add("status", "complete");
  } catch (error) {
    $("#api-status").textContent = "API unavailable";
    $("#api-status").classList.add("status", "error");
    toast(error.message);
  }
}

async function loadDashboard() {
  const dashboard = await request("/api/dashboard");
  const names = {
    terms: "Terms", courses: "Courses", instructors: "Instructors",
    rooms: "Rooms", student_groups: "Student groups", timeslots: "Timeslots",
    classes: "Classes",
  };
  $("#metrics").innerHTML = Object.entries(dashboard.counts).map(([key, value]) => `
    <div class="metric"><span>${escapeHtml(names[key] || key)}</span><strong>${value}</strong></div>
  `).join("");
  $("#recent-runs").innerHTML = dashboard.recent_runs.length
    ? dashboard.recent_runs.map((run) => `
      <tr><td><a class="text-link run-link" href="#${escapeHtml(run.id)}" data-run="${escapeHtml(run.id)}">${escapeHtml(run.id.slice(0, 8))}</a></td>
      <td>${escapeHtml(run.algorithm)}</td><td>${statusBadge(run.status)}</td><td>${escapeHtml(run.created_at)}</td></tr>
    `).join("")
    : '<tr><td colspan="4" class="muted">No runs yet. Create the first validated schedule from the Schedule page.</td></tr>';
  document.querySelectorAll(".run-link").forEach((link) => link.addEventListener("click", async (event) => {
    event.preventDefault();
    await showRun(link.dataset.run);
    showView("schedule");
  }));
  await loadTerms();
}

async function loadTerms() {
  const data = await request("/api/academic/terms");
  const options = data.items.map((term) =>
    `<option value="${term.id}">${escapeHtml(term.name)}${term.active ? " · active" : ""}</option>`
  ).join("");
  $("#term-select").innerHTML = options || '<option value="">Create a term first</option>';
}

async function loadResource() {
  state.resource = $("#resource-select").value;
  $("#csv-template").href = `/api/templates/${state.resource}`;
  const data = await request(`/api/academic/${state.resource}`);
  const fields = resourceFields[state.resource];
  const visible = ["id", ...fields.filter((field) => field !== "active" && field !== "room_required" && field !== "group_ids").slice(0, 5)];
  $("#resource-head").innerHTML = `<tr>${visible.map((field) => `<th>${escapeHtml(field.replaceAll("_", " "))}</th>`).join("")}<th>Actions</th></tr>`;
  $("#resource-rows").innerHTML = data.items.length ? data.items.map((row) => `
    <tr>${visible.map((field) => `<td>${escapeHtml(row[field])}</td>`).join("")}
    <td><button class="secondary row-edit" data-id="${row.id}">Edit</button>
    <button class="danger row-delete" data-id="${row.id}">Delete</button></td></tr>
  `).join("") : `<tr><td colspan="${visible.length + 1}" class="muted">No ${escapeHtml(labels[state.resource].toLowerCase())} yet.</td></tr>`;
  $("#resource-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"} · showing ${data.items.length}`;
  document.querySelectorAll(".row-edit").forEach((button) => button.addEventListener("click", () => {
    const item = data.items.find((row) => row.id === Number(button.dataset.id));
    openRecordForm(item);
  }));
  document.querySelectorAll(".row-delete").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Delete this record? Related database rules may prevent deletion.")) return;
    try {
      await request(`/api/academic/${state.resource}/${button.dataset.id}`, { method: "DELETE" });
      toast("Record deleted.");
      await loadResource();
    } catch (error) { toast(error.message); }
  }));
}

function openRecordForm(record = null) {
  state.editingId = record ? record.id : null;
  $("#dialog-title").textContent = `${record ? "Edit" : "Add"} ${labels[state.resource].toLowerCase().replace(/s$/, "")}`;
  const fields = resourceFields[state.resource];
  $("#record-fields").innerHTML = fields.map((field) => {
    const label = field.replaceAll("_", " ");
    const value = record?.[field] ?? (field === "duration" || field === "length" ? 2 : "");
    if (booleanFields.has(field)) {
      const checked = record ? Boolean(record[field]) : field === "active" || field === "room_required";
      return `<label>${escapeHtml(label)}<select name="${field}"><option value="true" ${checked ? "selected" : ""}>Yes</option><option value="false" ${!checked ? "selected" : ""}>No</option></select></label>`;
    }
    const type = integerFields.has(field) ? "number" : "text";
    const hint = field.endsWith("_ids") || field === "group_ids" ? ' placeholder="IDs separated by commas"' : "";
    const req = ["name", "start_date", "end_date", "term_id", "code", "capacity", "label", "days", "start", "length", "weeks", "course_id", "duration"].includes(field) ? "required" : "";
    return `<label>${escapeHtml(label)}<input name="${field}" type="${type}" value="${escapeHtml(value)}"${hint} ${req}></label>`;
  }).join("");
  $("#record-dialog").showModal();
}

async function saveRecord(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const data = {};
  for (const [key, value] of form.entries()) {
    data[key] = booleanFields.has(key) ? value === "true" : value;
    if (integerFields.has(key) && value !== "") data[key] = Number(value);
  }
  try {
    const path = `/api/academic/${state.resource}${state.editingId ? `/${state.editingId}` : ""}`;
    await request(path, {
      method: state.editingId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    $("#record-dialog").close();
    toast("Record saved.");
    await loadResource();
    await loadDashboard();
  } catch (error) { toast(error.message); }
}

async function importCsv(file) {
  const text = await file.text();
  try {
    const result = await request(`/api/import/csv/${state.resource}`, {
      method: "POST", headers: { "Content-Type": "text/csv" }, body: text,
    });
    toast(`Imported ${result.imported} records.`);
    await loadResource();
    await loadDashboard();
  } catch (error) { toast(error.message); }
  $("#csv-file").value = "";
}

function showView(name) {
  document.querySelectorAll(".view").forEach((section) => section.classList.add("hidden"));
  $(`#view-${name}`).classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $("#page-title").textContent = { dashboard: "Overview", academic: "Academic data", schedule: "Schedule", imports: "Imports" }[name];
  if (name === "academic") loadResource().catch((error) => toast(error.message));
  if (name === "imports") loadDatasets().catch((error) => toast(error.message));
  if (name === "schedule") loadTerms().catch((error) => toast(error.message));
}

async function runSchedule(source) {
  const body = {
    [source.key]: source.id,
    algorithm: "cp-sat",
    time_limit_s: Number($("#time-limit").value),
  };
  try {
    const created = await request("/api/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.jobId = created.id;
    $("#cancel-job").classList.remove("hidden");
    setCallout("#job-message", `Run ${created.id} queued. Waiting for the solver…`);
    await pollJob(created.id);
  } catch (error) {
    setCallout("#job-message", error.message, true);
  }
}

async function pollJob(identifier) {
  while (state.jobId === identifier) {
    try {
      const job = await request(`/api/jobs/${identifier}`);
      setCallout("#job-message", `${job.status.replaceAll("_", " ")} · ${job.error || "Solver is working."}`, job.status === "error");
      if (terminalStatuses.has(job.status)) {
        state.jobId = null;
        $("#cancel-job").classList.add("hidden");
        if (job.result) renderSchedule(job);
        if (job.status === "complete") toast("Complete schedule independently validated.");
        else toast(`Run finished: ${job.status.replaceAll("_", " ")}`);
        await loadDashboard();
        return;
      }
    } catch (error) {
      state.jobId = null;
      $("#cancel-job").classList.add("hidden");
      setCallout("#job-message", error.message, true);
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 650));
  }
}

async function cancelJob() {
  if (!state.jobId) return;
  try {
    const result = await request(`/api/jobs/${state.jobId}/cancel`, { method: "POST" });
    setCallout("#job-message", `Cancellation requested · ${result.status}`);
  } catch (error) { setCallout("#job-message", error.message, true); }
}

async function showRun(identifier) {
  try {
    const run = await request(`/api/schedules/${identifier}`);
    renderSchedule(run);
  } catch (error) { toast(error.message); }
}

async function loadCurrentSchedule() {
  try {
    const run = await request("/api/schedules/current");
    renderSchedule(run);
  } catch (error) { toast(error.message); }
}

async function renderSchedule(run) {
  const result = run.result;
  const validation = result?.validation;
  if (!result) return;
  const isValid = run.status === "complete" && result.successful && validation?.valid_complete;
  const notes = validation?.coverage_notes || [];
  const problems = validation?.required_distribution_violations?.length || 0;
  const unsupported = validation?.unsupported_constraints?.filter((item) => item.required).length || 0;
  $("#validation-summary").innerHTML = `
    <div class="${isValid ? "validation-good" : "validation-bad"}">
      <strong>${isValid ? "Complete, independently validated timetable" : "Not a validated complete timetable"}</strong><br>
      Status: ${escapeHtml(run.status.replaceAll("_", " "))} · Coverage: ${Math.round((result.assignment_coverage || 0) * 100)}%
      (${validation?.assigned_count || 0}/${validation?.total_classes || 0}) · Runtime: ${Number(result.runtime_s || 0).toFixed(2)}s
      · Objective: ${result.objective_score ?? "not available"} · Required-rule violations: ${problems} · Unsupported required rules: ${unsupported}
      ${notes.length ? `<details><summary>Validation coverage notes</summary><ul>${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul></details>` : ""}
    </div>`;
  state.classNames = {};
  try {
    const classes = await request("/api/academic/classes");
    state.classNames = Object.fromEntries(classes.items.map((item) => [item.id, item.name]));
  } catch (_) { /* ITC data has no matching local academic-class names. */ }
  const assignments = result.assignments || [];
  $("#schedule-rows").innerHTML = assignments.length ? assignments.map((item) => `
    <tr><td>${escapeHtml(state.classNames[item.class_id] || `Class ${item.class_id}`)}</td>
    <td>${escapeHtml(item.room_id ?? "No room")}</td><td>${escapeHtml(item.days)}</td>
    <td>${escapeHtml(item.start)}</td><td>${escapeHtml(item.length)}</td><td>${escapeHtml(item.weeks)}</td>
    <td class="domain-cell" data-class="${item.class_id}">Loading…</td></tr>
  `).join("") : '<tr><td colspan="7" class="muted">This run contains no assignments.</td></tr>';
  document.querySelectorAll(".domain-cell").forEach((cell) => {
    loadPlacementOptions(run.id, Number(cell.dataset.class), cell);
  });
  $("#export-links").innerHTML = run.status === "complete"
    ? `<a class="text-link" href="/api/exports/${encodeURIComponent(run.id)}.csv">CSV</a> &nbsp; <a class="text-link" href="/api/exports/${encodeURIComponent(run.id)}.xlsx">Excel</a>`
    : "";
}

async function loadPlacementOptions(runId, classId, cell) {
  try {
    const data = await request(`/api/schedules/${encodeURIComponent(runId)}/domains/${classId}`);
    const run = await request(`/api/schedules/${encodeURIComponent(runId)}`);
    const selected = run.result.assignments.find((item) => item.class_id === classId);
    const selectedIndex = data.placements.findIndex((item) =>
      item.room_id === selected.room_id && item.days === selected.days
      && item.start === selected.start && item.length === selected.length
      && item.weeks === selected.weeks
    );
    const options = data.placements.map((item) =>
      `<option value="${item.placement_index}" ${item.placement_index === selectedIndex ? "selected" : ""}>Room ${escapeHtml(item.room_id ?? "—")} · ${escapeHtml(item.days)} · ${escapeHtml(item.start)}</option>`
    ).join("");
    cell.innerHTML = `<select aria-label="Change class ${classId} placement">${options}</select>`;
    cell.querySelector("select").addEventListener("change", async (event) => {
      try {
        await request(`/api/schedules/${encodeURIComponent(runId)}/assignments/${classId}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ placement_index: Number(event.target.value) }),
        });
        toast("Schedule edit validated and saved.");
        await showRun(runId);
        await loadDashboard();
      } catch (error) {
        toast(`Edit rejected: ${error.message}`);
        await showRun(runId);
      }
    });
  } catch (error) { cell.textContent = error.message; }
}

async function loadDatasets() {
  const result = await request("/api/datasets");
  $("#dataset-rows").innerHTML = result.items.length ? result.items.map((dataset) => `
    <tr><td>${escapeHtml(dataset.name)}</td><td>${escapeHtml(dataset.format)}</td><td>${escapeHtml(dataset.created_at)}</td>
    <td><button class="secondary dataset-run" data-id="${dataset.id}">Run CP-SAT</button></td></tr>
  `).join("") : '<tr><td colspan="4" class="muted">No imported instances.</td></tr>';
  document.querySelectorAll(".dataset-run").forEach((button) => button.addEventListener("click", () => {
    showView("schedule");
    runSchedule({ key: "dataset_id", id: Number(button.dataset.id) });
  }));
}

async function importXml() {
  const file = $("#xml-file").files[0];
  if (!file) return toast("Choose an XML file first.");
  try {
    const source = await file.text();
    const name = encodeURIComponent($("#dataset-name").value || file.name);
    const result = await request(`/api/import/itc?name=${name}`, {
      method: "POST", headers: { "Content-Type": "application/xml" }, body: source,
    });
    setCallout("#import-message", `Imported ${result.name}: ${result.classes} classes, ${result.rooms} rooms, ${result.distributions} distributions.`);
    $("#xml-file").value = "";
    await loadDatasets();
    await loadDashboard();
  } catch (error) { setCallout("#import-message", error.message, true); }
}

document.querySelectorAll(".nav-item").forEach((button) =>
  button.addEventListener("click", () => showView(button.dataset.view))
);
document.querySelectorAll("[data-go]").forEach((button) =>
  button.addEventListener("click", () => showView(button.dataset.go))
);
$("#refresh-dashboard").addEventListener("click", () => loadDashboard().catch((error) => toast(error.message)));
$("#resource-select").addEventListener("change", () => loadResource().catch((error) => toast(error.message)));
$("#refresh-resource").addEventListener("click", () => loadResource().catch((error) => toast(error.message)));
$("#add-record").addEventListener("click", () => openRecordForm());
$("#record-form").addEventListener("submit", saveRecord);
$("#close-dialog").addEventListener("click", () => $("#record-dialog").close());
$("#cancel-dialog").addEventListener("click", () => $("#record-dialog").close());
$("#csv-file").addEventListener("change", (event) => {
  if (event.target.files[0]) importCsv(event.target.files[0]);
});
$("#run-solver").addEventListener("click", () => {
  const id = Number($("#term-select").value);
  if (id) runSchedule({ key: "term_id", id });
  else toast("Choose or create a term first.");
});
$("#cancel-job").addEventListener("click", cancelJob);
$("#load-current").addEventListener("click", loadCurrentSchedule);
$("#import-xml").addEventListener("click", importXml);
loadHealth();
loadDashboard().catch((error) => toast(error.message));
