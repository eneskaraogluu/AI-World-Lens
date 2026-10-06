const LOCAL_API_HOSTS = new Set(["localhost", "127.0.0.1"]);
const API_ORIGIN = LOCAL_API_HOSTS.has(window.location?.hostname || "localhost") ? "http://localhost:8000" : "";
const API_BASE = `${API_ORIGIN}/api`;

async function apiJson(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    try {
        payload = await response.json();
    } catch (_) {
        payload = null;
    }
    if (!response.ok) {
        throw new Error(payload?.detail || payload?.message || `API error (${response.status})`);
    }
    return payload;
}

const fetchHealth = () => apiJson(`${API_BASE}/health`);
const fetchCategories = () => apiJson(`${API_BASE}/categories`);
const fetchPrompts = () => apiJson(`${API_BASE}/prompts`);
const experimentQuery = (experimentId) => experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : "";
const fetchComparison = (promptId, experimentId = null) => apiJson(`${API_BASE}/comparison/prompts/${promptId}${experimentQuery(experimentId)}`);
const fetchImages = (promptId, experimentId = null) => apiJson(`${API_BASE}/comparison/prompts/${promptId}/images${experimentQuery(experimentId)}`);
const fetchExperimentStatus = (experimentId) => apiJson(`${API_BASE}/experiments/${experimentId}/status`);
const fetchExperimentTrajectory = (experimentId) => apiJson(`${API_BASE}/experiments/${experimentId}/trajectory`);
const fetchExperiments = (promptId = null) => apiJson(`${API_BASE}/experiments${promptId ? `?prompt_id=${encodeURIComponent(promptId)}` : ""}`);
const fetchExperimentComparison = (experimentId) => apiJson(`${API_BASE}/comparison/experiments/${experimentId}`);
const fetchExperimentResults = (experimentId) => apiJson(`${API_BASE}/experiments/${experimentId}/results`);
const reanalyzeExperiment = (experimentId, provider = "openai") => apiJson(`${API_BASE}/experiments/${experimentId}/reanalyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
});
const fetchPresentationBackups = () => apiJson(`${API_BASE}/presentation/backups`);
const fetchActivePresentationBackup = () => apiJson(`${API_BASE}/presentation/backups/active`);
const createPresentationBackup = (experimentId, name = null) => apiJson(`${API_BASE}/presentation/backups/from-experiment/${experimentId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
});
const activatePresentationBackup = (backupId) => apiJson(`${API_BASE}/presentation/backups/${backupId}/activate`, { method: "POST" });
const verifyPresentationBackup = (backupId) => apiJson(`${API_BASE}/presentation/backups/${backupId}/verify`, { method: "POST" });
const fetchPresentationReplay = (backupId) => apiJson(`${API_BASE}/presentation/backups/${backupId}/replay`);
const markPresentationReplay = (backupId) => apiJson(`${API_BASE}/presentation/backups/${backupId}/mark-replayed`, { method: "POST" });
const runPresentationPreflight = () => apiJson(`${API_BASE}/presentation/preflight`);

async function runExperiment(promptId, iterations) {
    const experiment = await apiJson(`${API_BASE}/experiments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: `Dashboard run ${new Date().toISOString()}`,
            model_name: "OpenAI GPT Image + Gemini Vision",
        }),
    });

    await apiJson(`${API_BASE}/experiments/${experiment.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_id: promptId, iterations }),
    });
    return experiment;
}
