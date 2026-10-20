"use strict";

const STATUSES = ["new", "saved", "applied", "interview", "offer", "rejected", "archived"];
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let currentFilter = "";
let currentJobId = null;

// --- API ----------------------------------------------------------------------

async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") opts.headers["X-JobSearch"] = "1";
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), error ? 7000 : 3500);
}

async function busy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { button.disabled = false; button.textContent = original; }
}

// --- Tabs ---------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${name}`));
  if (name === "jobs") loadJobs();
  if (name === "profile") loadProfile();
  if (name === "search") loadPortals();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// --- Status banner --------------------------------------------------------------

async function loadStatus() {
  const s = await api("/api/status");
  const issues = [];
  if (!s.api_key_set) issues.push("ANTHROPIC_API_KEY is not set, so fit scoring and document drafting won't work. Set it and restart the app.");
  if (!s.bun_installed) issues.push("Bun is not installed, so job board search won't work. You can still add jobs by URL or by pasting the text.");
  if (!s.profile_ready) issues.push("Your profile is empty. Start on the Profile tab.");
  const banner = $("#banner");
  banner.hidden = issues.length === 0;
  banner.innerHTML = issues.map(esc).join("<br>");
}

// --- Jobs list ------------------------------------------------------------------

function scoreClass(score) { return score >= 60 ? "good" : score >= 45 ? "mid" : "bad"; }

async function loadJobs() {
  const [jobs, stats] = await Promise.all([
    api("/api/jobs" + (currentFilter ? `?status=${currentFilter}` : "")),
    api("/api/stats"),
  ]);
  const total = Object.values(stats).reduce((a, b) => a + b, 0);
  $("#status-filter").innerHTML = [["", `All (${total})`], ...STATUSES.map((s) => [s, `${s} (${stats[s] || 0})`])]
    .map(([v, label]) => `<button class="chip${v === currentFilter ? " active" : ""}" data-status="${v}">${esc(label)}</button>`).join("");
  const applied = ["applied", "interview", "offer", "rejected"].reduce((a, s) => a + (stats[s] || 0), 0);
  const responded = (stats.interview || 0) + (stats.offer || 0);
  $("#stats").innerHTML = `<span><b>${applied}</b>applications</span><span><b>${stats.interview || 0}</b>interviewing</span>` +
    `<span><b>${stats.offer || 0}</b>offers</span><span><b>${applied ? Math.round((100 * responded) / applied) : 0}%</b>interview rate</span>`;

  const list = $("#job-list");
  if (!jobs.length) {
    list.innerHTML = `<div class="empty">No jobs here yet. Search job boards under <b>Find jobs</b>, or use <b>+ Add job</b> to add one by URL or text.</div>`;
    return;
  }
  list.innerHTML = jobs.map((j) => `
    <button class="job" data-id="${j.id}">
      <div class="title">${esc(j.title || "Untitled")}</div>
      <div class="meta">${esc([j.company, j.location, j.posted].filter(Boolean).join(" · "))} · ${esc(j.source)}</div>
      <div class="side">
        <span class="badge">${esc(j.status)}</span>
        ${j.fit_score != null ? `<span class="score ${scoreClass(j.fit_score)}">${j.fit_score} · ${esc(j.fit_verdict)}</span>` : ""}
      </div>
    </button>`).join("");
}

$("#status-filter").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  currentFilter = chip.dataset.status;
  loadJobs();
});
$("#job-list").addEventListener("click", (e) => {
  const row = e.target.closest(".job");
  if (row) openJob(Number(row.dataset.id));
});

// --- Add job --------------------------------------------------------------------

$("#add-job-btn").addEventListener("click", () => { $("#add-form").reset(); $("#add-dialog").showModal(); });
$("#add-cancel").addEventListener("click", () => $("#add-dialog").close());
$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  const btn = e.submitter;
  await busy(btn, "Adding…", async () => {
    const job = await api("/api/jobs", { method: "POST", body });
    $("#add-dialog").close();
    loadJobs();
    openJob(job.id);
  });
});

// --- Job detail -----------------------------------------------------------------

function closeJob() { $("#detail").hidden = true; currentJobId = null; }
$("#detail-close").addEventListener("click", closeJob);
$("#detail").addEventListener("click", (e) => { if (e.target.id === "detail") closeJob(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#detail").hidden) closeJob(); });

function renderFit(job) {
  const f = job.fit;
  if (!f) return `<p class="muted">Not evaluated yet.</p>`;
  const gate = (name, g) => `<span class="gate ${g.verdict}" title="${esc(g.note)}">${name}: ${g.verdict}</span>`;
  const dim = (label, d) => `<div class="dim"><b>${label} · ${d.score}</b><div class="bar"><span style="width:${d.score}%"></span></div>${esc(d.reasoning)}</div>`;
  const notes = [["Eligibility", f.eligibility], ["Language", f.language], ["Location", f.location]]
    .filter(([, g]) => g.verdict !== "PASS" || g.note).map(([n, g]) => `<li><b>${n}:</b> ${esc(g.note)}</li>`).join("");
  return `
    <div class="verdict"><span class="score ${scoreClass(job.fit_score)}">${job.fit_score}</span> · ${esc(job.fit_verdict)}</div>
    ${job.guard_verdict ? `<div class="guard">Posting check: ${esc(job.guard_verdict)}</div>` : ""}
    <div class="gates" style="margin:8px 0">${gate("Eligibility", f.eligibility)}${gate("Language", f.language)}${gate("Location", f.location)}</div>
    ${notes ? `<ul class="tight">${notes}</ul>` : ""}
    <div class="dims">${dim("Technical skills", f.technical_skills)}${dim("Experience", f.experience)}${dim("Culture", f.culture)}${dim("Career alignment", f.career_alignment)}</div>
    <h3>Strengths</h3><ul class="tight">${f.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
    <h3>Gaps</h3><ul class="tight">${f.gaps.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
    <h3>Recommendation</h3><p>${esc(f.recommendation)}</p>`;
}

function renderDocs(job) {
  const d = job.documents;
  if (!d) return `<p class="muted">No CV or cover letter yet.</p>`;
  return `
    <div class="row-actions">
      <a href="/jobs/${job.id}/cv" target="_blank" rel="noopener"><button>Open CV</button></a>
      <a href="/jobs/${job.id}/cover" target="_blank" rel="noopener"><button>Open cover letter</button></a>
      <span class="muted">Generated ${esc(d.created_at.slice(0, 16).replace("T", " "))}. Use Print → Save as PDF in the page that opens.</span>
    </div>
    ${d.keywords_missing.length ? `<p><b>Keywords from the posting your profile doesn't support:</b> ${esc(d.keywords_missing.join(", "))}</p>` : ""}
    <p class="muted"><b>Covered:</b> ${esc(d.keywords_covered.join(", "))}</p>`;
}

async function openJob(id) {
  currentJobId = id;
  const job = await api(`/api/jobs/${id}`);
  $("#detail").hidden = false;
  $("#detail-body").innerHTML = `
    <div class="detail-head">
      <h2>${esc(job.title || "Untitled")}</h2>
      <div class="muted">${esc([job.company, job.location, job.posted].filter(Boolean).join(" · "))}</div>
      ${job.url ? `<a href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">View original posting</a>` : ""}
    </div>
    <div class="row-actions">
      <label style="flex-direction:row;align-items:center;gap:6px">Status
        <select id="d-status">${STATUSES.map((s) => `<option${s === job.status ? " selected" : ""}>${s}</option>`).join("")}</select>
      </label>
      ${job.applied_at ? `<span class="muted">Applied ${esc(job.applied_at)}</span>` : ""}
      <span style="flex:1"></span>
      <button class="danger" id="d-delete">Delete</button>
    </div>

    <h3>Fit</h3>
    <div class="row-actions"><button class="primary" id="d-evaluate">${job.fit ? "Re-evaluate" : "Evaluate fit"}</button></div>
    ${renderFit(job)}

    <h3>CV and cover letter</h3>
    <label>Notes for this application (optional)<textarea id="d-tailor-notes" rows="2" placeholder="e.g. emphasise my stakeholder work; I know the hiring manager's name is Sam Lee"></textarea></label>
    <div class="row-actions"><button class="primary" id="d-generate">${job.documents ? "Regenerate" : "Generate CV + cover letter"}</button></div>
    ${renderDocs(job)}

    <h3>Notes</h3>
    <textarea id="d-notes" rows="3" placeholder="Contacts, interview dates, follow-ups...">${esc(job.notes)}</textarea>
    <div class="row-actions"><button id="d-save-notes">Save notes</button></div>

    <h3>Posting</h3>
    <div class="row-actions"><button id="d-fetch">${job.description ? "Re-fetch description" : "Fetch description"}</button></div>
    <div class="description">${esc(job.description) || '<span class="muted">No description yet.</span>'}</div>`;

  $("#d-status").addEventListener("change", async (e) => {
    try { await api(`/api/jobs/${id}`, { method: "PATCH", body: { status: e.target.value } }); toast("Status updated"); openJob(id); loadJobs(); }
    catch (err) { toast(err.message, true); }
  });
  $("#d-delete").addEventListener("click", async () => {
    if (!confirm("Delete this job and its documents?")) return;
    await api(`/api/jobs/${id}`, { method: "DELETE" });
    closeJob(); loadJobs();
  });
  $("#d-evaluate").addEventListener("click", (e) => busy(e.target, "Evaluating… (about 30s)", async () => {
    await api(`/api/jobs/${id}/evaluate`, { method: "POST" });
    if (currentJobId === id) openJob(id);
    loadJobs();
  }));
  $("#d-generate").addEventListener("click", (e) => busy(e.target, "Writing… (about a minute)", async () => {
    await api(`/api/jobs/${id}/documents`, { method: "POST", body: { notes: $("#d-tailor-notes").value } });
    if (currentJobId === id) openJob(id);
    toast("CV and cover letter ready");
  }));
  $("#d-save-notes").addEventListener("click", (e) => busy(e.target, "Saving…", async () => {
    await api(`/api/jobs/${id}`, { method: "PATCH", body: { notes: $("#d-notes").value } });
    toast("Notes saved");
  }));
  $("#d-fetch").addEventListener("click", (e) => busy(e.target, "Fetching…", async () => {
    await api(`/api/jobs/${id}/fetch`, { method: "POST" });
    openJob(id);
  }));
}

// --- Search ---------------------------------------------------------------------

let portalsLoaded = false;
async function loadPortals() {
  if (portalsLoaded) return;
  const portals = await api("/api/portals");
  $("#portal-list").innerHTML = portals.map((p) =>
    `<label><input type="checkbox" name="portal" value="${esc(p.name)}"${p.enabled ? " checked" : ""}>${esc(p.name.replace(/-search$/, ""))}${p.takes_location ? "" : ' <span class="muted">(keywords only)</span>'}</label>`).join("");
  portalsLoaded = true;
}

$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = { query: fd.get("query"), location: fd.get("location"), jobage: Number(fd.get("jobage")), portals: fd.getAll("portal") };
  if (!body.portals.length) return toast("Pick at least one job board", true);
  await busy(e.submitter, "Searching…", async () => {
    const r = await api("/api/search", { method: "POST", body });
    $("#search-result").innerHTML = `Added <b>${r.added}</b> new jobs (${r.already_seen} already in your list).` +
      (r.errors.length ? `<br><span style="color:var(--bad)">${r.errors.map(esc).join("<br>")}</span>` : "") +
      (r.added ? ` <a href="#" id="see-new">See new jobs</a>` : "");
    const link = $("#see-new");
    if (link) link.addEventListener("click", (ev) => { ev.preventDefault(); currentFilter = "new"; showTab("jobs"); });
  });
});

// --- Profile --------------------------------------------------------------------

const TEXT_FIELDS = [["name", "Full name"], ["email", "Email"], ["phone", "Phone"], ["location", "Location"], ["linkedin", "LinkedIn URL"], ["headline", "Headline"]];
const AREA_FIELDS = [["summary", "Summary"], ["strengths", "Strengths"], ["work_style", "How you like to work"], ["career_goals", "Career goals"], ["work_rights", "Work rights (citizenship, visas)"]];
const LIST_FIELDS = [["primary_skills", "Primary skills"], ["secondary_skills", "Secondary skills"], ["tools", "Tools and software"], ["certifications", "Certifications"], ["target_roles", "Target roles"], ["target_locations", "Target locations (or Remote)"], ["dealbreakers", "Deal-breakers"]];
const REPEATS = {
  experience: { label: "Experience", fields: [["title", "Title"], ["company", "Company"], ["location", "Location"], ["start", "Start"], ["end", "End"]], bullets: true },
  education: { label: "Education", fields: [["degree", "Degree"], ["institution", "Institution"], ["start", "Start"], ["end", "End"], ["details", "Details"]] },
  languages: { label: "Languages", fields: [["language", "Language"], ["level", "Level"]] },
};

function repeatItem(kind, item = {}) {
  const spec = REPEATS[kind];
  return `<div class="repeat" data-kind="${kind}">
    <div class="repeat-head"><b>${spec.label.replace(/s$/, "")}</b><button type="button" class="danger remove">Remove</button></div>
    <div class="form-row">${spec.fields.map(([k, l]) => `<label>${l}<input data-k="${k}" value="${esc(item[k])}"></label>`).join("")}</div>
    ${spec.bullets ? `<label>Bullets (one per line)<textarea data-k="bullets" rows="4">${esc((item.bullets || []).join("\n"))}</textarea></label>` : ""}
  </div>`;
}

function renderProfile(p) {
  $("#profile-form").innerHTML = `
    <h2>Your profile</h2>
    <p class="muted">Every CV and cover letter is built from this, and Claude is told never to add anything that isn't here. It's saved only on this computer, in data/profile.json.</p>
    <div class="form-row">${TEXT_FIELDS.map(([k, l]) => `<label>${l}<input name="${k}" value="${esc(p[k])}"></label>`).join("")}</div>
    ${AREA_FIELDS.map(([k, l]) => `<label>${l}<textarea name="${k}" rows="3">${esc(p[k])}</textarea></label>`).join("")}
    ${LIST_FIELDS.map(([k, l]) => `<label>${l} (one per line)<textarea name="${k}" rows="3">${esc((p[k] || []).join("\n"))}</textarea></label>`).join("")}
    ${Object.entries(REPEATS).map(([kind, spec]) => `
      <h3>${spec.label}</h3>
      <div class="stack" id="rep-${kind}">${(p[kind] || []).map((it) => repeatItem(kind, it)).join("")}</div>
      <div><button type="button" class="add-rep" data-kind="${kind}">+ Add ${spec.label.replace(/s$/, "").toLowerCase()}</button></div>`).join("")}
    <div class="actions"><button class="primary" type="submit">Save profile</button></div>`;
}

function readProfile() {
  const form = $("#profile-form");
  const p = {};
  TEXT_FIELDS.concat(AREA_FIELDS).forEach(([k]) => (p[k] = form.elements[k].value.trim()));
  LIST_FIELDS.forEach(([k]) => (p[k] = form.elements[k].value.split("\n").map((s) => s.trim()).filter(Boolean)));
  Object.keys(REPEATS).forEach((kind) => {
    p[kind] = [...form.querySelectorAll(`.repeat[data-kind="${kind}"]`)].map((el) => {
      const item = {};
      el.querySelectorAll("[data-k]").forEach((input) => {
        item[input.dataset.k] = input.dataset.k === "bullets"
          ? input.value.split("\n").map((s) => s.replace(/^[-•*]\s*/, "").trim()).filter(Boolean)
          : input.value.trim();
      });
      return item;
    });
  });
  return p;
}

async function loadProfile() { renderProfile(await api("/api/profile")); }

$("#profile-form").addEventListener("click", (e) => {
  if (e.target.classList.contains("remove")) e.target.closest(".repeat").remove();
  if (e.target.classList.contains("add-rep")) {
    const kind = e.target.dataset.kind;
    $(`#rep-${kind}`).insertAdjacentHTML("beforeend", repeatItem(kind));
  }
});
$("#profile-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await busy(e.submitter, "Saving…", async () => {
    renderProfile(await api("/api/profile", { method: "PUT", body: readProfile() }));
    toast("Profile saved");
    loadStatus();
  });
});
$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  await busy(e.submitter, "Reading your CV…", async () => {
    renderProfile(await api("/api/profile/import", { method: "POST", form }));
    toast("Imported. Check the details, then Save profile.");
  });
});

// --- Init -----------------------------------------------------------------------

loadStatus().catch(() => {});
loadJobs().catch((e) => toast(e.message, true));
