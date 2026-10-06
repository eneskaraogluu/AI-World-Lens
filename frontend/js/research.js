const RESEARCH_API_ORIGIN = ["localhost", "127.0.0.1"].includes(window.location?.hostname || "localhost")
    ? "http://localhost:8000"
    : "";
const API = `${RESEARCH_API_ORIGIN}/api/research`;
const HEALTH_API = `${RESEARCH_API_ORIGIN}/api/health`;
const state = { studies: [], waves: [], prompts: [], campaigns: [], selectedPrompts: new Set(), view: "campaigns", atlasSource: null };

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, options);
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) throw new Error(payload?.detail || `Research API error (${response.status})`);
    return payload;
}
function jsonOptions(body) { return { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) }; }
function toast(message, type = "success") { const el = $("research-toast"); el.textContent = message; el.className = `research-toast ${type}`; el.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 5200); }

async function checkHealth() {
    const chip = $("research-health");
    try {
        const response = await fetch(HEALTH_API); const health = await response.json();
        chip.className = `health-chip ${health.research_storage_ready ? "ready" : "error"}`;
        chip.querySelector("span").textContent = health.research_storage_ready ? "Research storage ready" : "Research migration required";
    } catch (_) { chip.className = "health-chip error"; chip.querySelector("span").textContent = "Backend unavailable"; }
}

async function loadStudies() {
    state.studies = await api("/studies");
    const select = $("study-select"); const current = select.value;
    select.innerHTML = `<option value="">Choose a study</option>${state.studies.map(item => `<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("")}`;
    if (state.studies.some(item => item.id === current)) select.value = current;
}
async function selectStudy(studyId) {
    state.waves = [];
    if (studyId) { const study = await api(`/studies/${studyId}`); state.waves = study.waves || []; }
    renderWaveOptions(); $("create-wave").disabled = !studyId; await loadCampaigns();
}
function renderWaveOptions() {
    const values = [`<option value="">Choose a wave</option>`, ...state.waves.map(wave => `<option value="${wave.id}">${escapeHtml(wave.label)} · ${escapeHtml(wave.status)}</option>`)].join("");
    $("wave-select").innerHTML = values; $("atlas-wave").innerHTML = values;
    renderWaveManifest(null); updateCampaignButton();
}
function renderWaveManifest(wave) {
    $("wave-manifest").textContent = wave ? `${wave.generator_provider}/${wave.generator_model} → ${wave.analyzer_provider}/${wave.analyzer_model}\nProtocol ${wave.prompt_set_version} · benchmark ${wave.benchmark_version}\n${wave.locked_at ? `Locked ${new Date(wave.locked_at).toLocaleString()}` : "Not locked until its first campaign plan"}` : "Select a wave to inspect its frozen provider snapshot.";
}

async function loadPrompts() {
    const language = $("prompt-language").value;
    state.prompts = await api(`/prompts?language=${encodeURIComponent(language)}`);
    const categories = [...new Set(state.prompts.map(item => item.category))].sort();
    const categorySelect = $("prompt-category"); const current = categorySelect.value;
    categorySelect.innerHTML = `<option value="">All categories</option>${categories.map(item => `<option value="${escapeHtml(item)}">${escapeHtml(item.replaceAll("_", " "))}</option>`).join("")}`;
    if (categories.includes(current)) categorySelect.value = current;
    state.selectedPrompts = new Set([...state.selectedPrompts].filter(id => state.prompts.some(prompt => prompt.id === id)));
    renderPrompts();
}
function renderPrompts() {
    const category = $("prompt-category").value;
    const prompts = state.prompts.filter(item => !category || item.category === category);
    $("research-prompt-list").innerHTML = prompts.length ? prompts.map(item => `<label class="prompt-option"><input type="checkbox" data-prompt-id="${item.id}" ${state.selectedPrompts.has(item.id) ? "checked" : ""}><span><strong>${escapeHtml(item.prompt_text)}</strong><small>${escapeHtml(item.category.replaceAll("_", " "))} · ${escapeHtml(item.expected_person_policy)}</small></span><b>${escapeHtml(item.scene_policy.replaceAll("_", " "))}</b></label>`).join("") : `<p class="empty-message">No prompt matches this language and category.</p>`;
    $("prompt-count").textContent = `${state.selectedPrompts.size} selected`; updateWorkload();
}
function updateWorkload() { const target = Math.max(0, Number($("campaign-target").value) || 0); $("campaign-workload").textContent = `${(target * state.selectedPrompts.size).toLocaleString()} samples`; updateCampaignButton(); }
function updateCampaignButton() { $("create-campaign").disabled = !$("wave-select").value || !$("campaign-name").value.trim() || state.selectedPrompts.size === 0; }

async function createStudy() {
    const study = await api("/studies", jsonOptions({ title: $("study-title").value.trim(), slug: $("study-slug").value.trim(), research_question: $("study-question").value.trim(), theoretical_framework: "Cultivation-inspired representational audit", protocol_version: "1.0" }));
    await loadStudies(); $("study-select").value = study.id; await selectStudy(study.id); $("new-study-panel").open = false; toast("Study created. No provider call was made.");
}
async function createWave() {
    const studyId = $("study-select").value;
    const wave = await api(`/studies/${studyId}/waves`, jsonOptions({ label: $("wave-label").value.trim(), benchmark_version: $("benchmark-version").value.trim() || "unconfigured", prompt_set_version: "1.0", codebook_version: "1.0" }));
    await selectStudy(studyId); $("wave-select").value = wave.id; $("atlas-wave").value = wave.id; renderWaveManifest(wave); await loadCampaigns(); toast("Wave created with a frozen provider snapshot.");
}
async function createCampaign() {
    const campaign = await api("/campaigns", jsonOptions({ wave_id: $("wave-select").value, name: $("campaign-name").value.trim(), target_per_prompt: Number($("campaign-target").value), prompt_definition_ids: [...state.selectedPrompts], prompt_variant_ids: [] }));
    await loadCampaigns(); toast(`Campaign plan created: ${campaign.requested_total} persistent task slots. Nothing has been sent yet.`);
}

async function loadCampaigns() {
    const waveId = $("wave-select").value;
    if (!waveId) { state.campaigns = []; renderCampaigns(); return; }
    state.campaigns = await api(`/campaigns?wave_id=${encodeURIComponent(waveId)}`);
    const statuses = await Promise.all(state.campaigns.map(item => api(`/campaigns/${item.id}/status`).catch(() => null)));
    state.campaigns.forEach((item, index) => item.live = statuses[index]); renderCampaigns();
}
function actionButtons(campaign) {
    if (campaign.status === "draft") return `<button class="secondary-action" data-action="dry" data-id="${campaign.id}">Dry run</button><button class="primary-action" data-action="start" data-id="${campaign.id}">Start campaign</button>`;
    if (campaign.status === "running") return `<button class="secondary-action" data-action="dry" data-id="${campaign.id}">Dry run</button><button class="secondary-action" data-action="pause" data-id="${campaign.id}">Pause after active tasks</button>`;
    if (campaign.status === "paused") return `<button class="secondary-action" data-action="dry" data-id="${campaign.id}">Dry run</button><button class="primary-action" data-action="resume" data-id="${campaign.id}">Resume missing tasks</button>`;
    return `<button class="secondary-action" data-action="dry" data-id="${campaign.id}">Inspect plan</button>`;
}
function renderCampaigns() {
    const container = $("campaign-list");
    if (!state.campaigns.length) { container.innerHTML = `<div class="large-empty"><strong>No campaign in this wave.</strong><p>Create a plan above. Nothing is sent to a provider until you explicitly start it.</p></div>`; return; }
    container.innerHTML = state.campaigns.map(campaign => { const counts = campaign.live?.counts || {requested:campaign.requested_total,queued:0,processing:0,completed:campaign.completed_total,generated:campaign.generated_total,machine_validated:campaign.validated_total,human_annotated:0,unverified:campaign.unverified_total,failed:campaign.failed_total}; return `<article class="campaign-record" data-campaign-id="${campaign.id}"><header><div><small>${campaign.prompts.length} prompt arms · hash ${escapeHtml(campaign.prompt_set_hash.slice(0,10))}…</small><h3>${escapeHtml(campaign.name)}</h3></div><span class="status-pill">${escapeHtml(campaign.status)}</span></header><div class="campaign-counts" style="grid-template-columns:repeat(5,1fr);row-gap:18px">${[["Requested",counts.requested],["Queued",counts.queued],["Processing",counts.processing],["Completed",counts.completed],["Generated",counts.generated],["Machine validated",counts.machine_validated],["Human coded",counts.human_annotated],["Unverified",counts.unverified],["Failed",counts.failed],["Queue depth",campaign.live?.queue_depth||0]].map(([label,value]) => `<div><span>${label}</span><strong>${Number(value||0).toLocaleString()}</strong></div>`).join("")}</div><div class="campaign-actions"><small>${escapeHtml(campaign.live?.safe_message || "Machine-coded results remain provisional until human coding is implemented.")}</small>${actionButtons(campaign)}</div><div class="dry-run-box" hidden></div></article>`; }).join("");
}
async function campaignAction(action, id) {
    const record = document.querySelector(`[data-campaign-id="${id}"]`); const dry = record?.querySelector(".dry-run-box");
    if (action === "dry") { const plan = await api(`/campaigns/${id}/dry-run`); dry.hidden = false; dry.textContent = `DRY RUN · ${plan.missing_tasks} missing / ${plan.already_materialized} materialized · ${plan.prompt_count} prompt arms · ${plan.provider.generation} → ${plan.provider.analysis} · real API calls: no`; return; }
    if (action === "start" && !window.confirm("This starts real provider requests and may consume quota or incur charges. Start this campaign?")) return;
    await api(`/campaigns/${id}/${action}`, {method:"POST"}); await loadCampaigns(); toast(action === "pause" ? "Campaign paused. Active tasks may finish; no new task will be enqueued." : "Campaign state updated. Only missing persistent task slots are eligible.");
}

function switchView(view) {
    state.view = view; $("campaigns-view").hidden = view !== "campaigns"; $("atlas-view").hidden = view !== "atlas";
    document.querySelectorAll("[data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === view));
    $("view-title").textContent = view === "atlas" ? "Representation Atlas" : "Research Campaigns"; $("view-crumb").textContent = view === "atlas" ? "ATLAS" : "CAMPAIGNS";
    if (view === "atlas") refreshAtlas();
}
const atlasEvidenceMap = { female_gap:["visible_gender_presentation","Female"], age_55_gap:["estimated_age_group","55+"], urban_gap:["urbanicity","Urban"], occupation_alignment_gap:["occupation_alignment","Aligned"], high_technology_gap:["technology_presence","High"] };
async function refreshAtlas() {
    const waveId = $("atlas-wave").value || $("wave-select").value; if (!waveId) return renderAtlas(null); $("atlas-wave").value = waveId;
    await loadAtlasSources(waveId);
    const params = new URLSearchParams(); if ($("atlas-language").value) params.set("language", $("atlas-language").value); if ($("atlas-category").value) params.set("category", $("atlas-category").value);
    const sourceValue = $("atlas-analysis-source").value; state.atlasSource = sourceValue ? JSON.parse(sourceValue) : null;
    if (state.atlasSource) { params.set("provider", state.atlasSource.provider); params.set("model", state.atlasSource.model); params.set("revision", state.atlasSource.revision); }
    const data = await api(`/waves/${waveId}/atlas?${params}`); renderAtlas(data);
}
async function loadAtlasSources(waveId) {
    const select = $("atlas-analysis-source"); const current = select.value;
    const sources = await api(`/waves/${waveId}/analysis-sources`);
    select.innerHTML = `<option value="">Auto (single active source)</option>${sources.map(source => { const value = escapeHtml(JSON.stringify({provider:source.provider,model:source.model,revision:source.revision})); return `<option value='${value}'>${escapeHtml(source.provider)} / ${escapeHtml(source.model)} · rev ${source.revision} · n=${source.active_result_count}</option>`; }).join("")}`;
    if ([...select.options].some(option => option.value === current)) select.value = current;
    else if (sources.length === 1) select.selectedIndex = 1;
}
function metricCell(cell, promptId, waveId) {
    if (cell.status !== "value") return `<div class="metric-cell neutral"><strong>—</strong><span>${escapeHtml(cell.status.replaceAll("_", " "))}</span><small>n=${cell.n} · denominator=${cell.denominator}</small></div>`;
    const tone = cell.dimension === "validated_yield" ? "" : cell.value > 0 ? "positive" : cell.value < 0 ? "negative" : ""; const canOpen = atlasEvidenceMap[cell.dimension];
    return `<button class="metric-cell ${tone}" ${canOpen ? `data-evidence-prompt="${promptId}" data-evidence-wave="${waveId}" data-evidence-dimension="${cell.dimension}"` : "disabled"}><strong>${cell.value > 0 && cell.unit === "pp" ? "+" : ""}${cell.value}${escapeHtml(cell.unit || "")}</strong><span>${cell.generated_share == null ? "Campaign ledger" : `AI ${(cell.generated_share*100).toFixed(1)}% · ref ${(cell.reference_share*100).toFixed(1)}%`}</span><small>n=${cell.n} · denominator=${cell.denominator}</small></button>`;
}
function renderAtlas(data) {
    const tbody = $("atlas-table").querySelector("tbody"); $("atlas-source").textContent = data?.analysis_source || "No analysis source selected";
    if (!data?.rows?.length) { tbody.innerHTML = `<tr><td colspan="7" class="table-empty">No recorded campaign prompt evidence for this selection.</td></tr>`; return; }
    const categories = [...new Set(data.rows.map(row => row.category))].sort(); $("atlas-category").innerHTML = `<option value="">All</option>${categories.map(item => `<option value="${escapeHtml(item)}">${escapeHtml(item.replaceAll("_", " "))}</option>`).join("")}`;
    tbody.innerHTML = data.rows.map(row => `<tr><td><strong>${escapeHtml(row.prompt)}</strong><br><small>${escapeHtml(row.language)} · ${escapeHtml(row.category.replaceAll("_", " "))}</small></td>${row.cells.map(cell => `<td>${metricCell(cell,row.campaign_prompt_id,data.wave_id)}</td>`).join("")}</tr>`).join("");
}
async function openEvidence(button) {
    const [dimension, categoryValue] = atlasEvidenceMap[button.dataset.evidenceDimension]; const params = new URLSearchParams({campaign_prompt_id:button.dataset.evidencePrompt,dimension,category_value:categoryValue});
    if (state.atlasSource) { params.set("provider", state.atlasSource.provider); params.set("model", state.atlasSource.model); params.set("revision", state.atlasSource.revision); }
    const data = await api(`/waves/${button.dataset.evidenceWave}/atlas/evidence?${params}`); const drawer = $("evidence-drawer"); drawer.hidden = false; $("evidence-title").textContent = `${categoryValue} evidence`; $("evidence-context").textContent = `${data.items.length} active-revision records. Every item explains whether it contributes to this metric category.`;
    $("evidence-list").innerHTML = data.items.length ? data.items.map(item => `<article class="evidence-item">${item.image_reference ? `<img src="${escapeHtml(imageUrl(item.image_reference))}" alt="Generated campaign evidence" loading="lazy">` : ""}<div class="evidence-body"><strong>${escapeHtml(item.prompt)}</strong><p>${escapeHtml(item.inclusion_reason)}</p><div class="evidence-tags"><span>${escapeHtml(item.analyzer_provider)} / rev ${item.analyzer_revision}</span><span>${escapeHtml(item.source_type)}</span><span>${item.included_in_metric ? "INCLUDED" : "NOT IN CATEGORY"}</span><span>${escapeHtml(item.generation_model)}</span></div></div></article>`).join("") : `<p class="empty-message">No active-revision evidence is available for this cell.</p>`;
}
function imageUrl(reference) { if (reference.startsWith("blob:")) return `/api/assets/image?ref=${encodeURIComponent(reference)}`; if (/^https?:\/\//i.test(reference)) return reference; const file = reference.split(/[\\/]/).pop(); return `./assets/generations/${encodeURIComponent(file)}`; }

function bindEvents() {
    document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
    $("study-select").addEventListener("change", event => run(() => selectStudy(event.target.value)));
    $("wave-select").addEventListener("change", event => { const wave = state.waves.find(item => item.id === event.target.value); renderWaveManifest(wave); $("atlas-wave").value = event.target.value; run(loadCampaigns); updateCampaignButton(); });
    $("create-study").addEventListener("click", () => run(createStudy)); $("create-wave").addEventListener("click", () => run(createWave)); $("create-campaign").addEventListener("click", () => run(createCampaign));
    $("prompt-language").addEventListener("change", () => run(loadPrompts)); $("prompt-category").addEventListener("change", renderPrompts); $("campaign-target").addEventListener("input", updateWorkload); $("campaign-name").addEventListener("input", updateCampaignButton);
    $("research-prompt-list").addEventListener("change", event => { if (!event.target.dataset.promptId) return; event.target.checked ? state.selectedPrompts.add(event.target.dataset.promptId) : state.selectedPrompts.delete(event.target.dataset.promptId); renderPrompts(); });
    $("campaign-list").addEventListener("click", event => { const button = event.target.closest("[data-action]"); if (button) run(() => campaignAction(button.dataset.action, button.dataset.id)); });
    $("refresh-atlas").addEventListener("click", () => run(refreshAtlas)); $("atlas-wave").addEventListener("change", () => run(refreshAtlas));
    $("atlas-table").addEventListener("click", event => { const button = event.target.closest("[data-evidence-prompt]"); if (button) run(() => openEvidence(button)); });
    $("close-evidence").addEventListener("click", () => { $("evidence-drawer").hidden = true; });
}
async function run(operation) { try { await operation(); } catch (error) { toast(error.message || "Research operation failed.", "error"); } }
async function init() { bindEvents(); await checkHealth(); try { await Promise.all([loadStudies(), loadPrompts()]); if (state.studies.length) { $("study-select").value = state.studies[0].id; await selectStudy(state.studies[0].id); } } catch (error) { toast(error.message, "error"); } setInterval(() => { if (state.view === "campaigns" && state.campaigns.some(item => ["running","paused"].includes(item.status))) run(loadCampaigns); }, 3500); }
document.addEventListener("DOMContentLoaded", init);
