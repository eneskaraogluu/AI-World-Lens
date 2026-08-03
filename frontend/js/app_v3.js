let selectedPromptId = null;
let selectedPromptText = null;
let activeExperiment = null;
let charts = { gender: null, age: null };
let runIterations = 10;
let runActive = false;
let healthReady = false;
let elapsedTimer = null;
let lastFocusedElement = null;
let cinemaRenderedOrders = new Set();
let cinemaEventQueue = [];
let cinemaPlaying = false;
let cinemaVisible = false;
let cinemaFinishRequested = false;
let cinemaCloseTimer = null;
let cinemaPlaybackTimer = null;
let cinemaChartEvents = [];
let latestCinemaStatus = null;
let cinemaMode = "live";
let presentationMode = "live";
let cinemaCanonicalState = null;
let fallbackVisionConfigured = false;
let activePresentationBackup = null;
let selectedPresentationBackup = null;
let presentationBackups = [];
let currentComparison = null;
let currentExperimentResults = [];
let cinemaTrajectoryExperimentId = null;
let currentReplayPayload = null;
let cinemaReplayPaused = false;
let cinemaReplaySpeed = 1;
let cinemaActiveSample = null;
let cinemaImageRequestId = 0;
let comparisonTransitionActive = false;
let presentationContext = createPresentationContext();
const sessionExperimentIds = new Map();

Chart.defaults.color = "#94a3b8";
Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, sans-serif";
Chart.defaults.plugins.tooltip.backgroundColor = "#151c28";
Chart.defaults.plugins.tooltip.borderColor = "#354154";
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.padding = 12;

const chartValueLabels = {
    id: "worldLensValueLabels",
    afterDatasetsDraw(chart) {
        const { ctx } = chart;
        ctx.save();
        ctx.font = "500 9px DM Mono, monospace";
        ctx.fillStyle = "#d7dbea";
        ctx.textAlign = chart.options.indexAxis === "y" ? "left" : "center";
        chart.data.datasets.forEach((dataset, datasetIndex) => {
            const meta = chart.getDatasetMeta(datasetIndex);
            meta.data.forEach((bar, index) => {
                const value = Number(dataset.data[index]);
                if (!Number.isFinite(value)) return;
                const position = bar.tooltipPosition();
                if (chart.options.indexAxis === "y") ctx.fillText(`${value.toFixed(1)}%`, position.x + 6, position.y + 3);
                else ctx.fillText(`${value.toFixed(1)}%`, position.x, position.y - 7);
            });
        });
        ctx.restore();
    },
};

document.addEventListener("DOMContentLoaded", initializeApp);

async function initializeApp() {
    bindInterfaceEvents();
    setChartEmpty("gender", true);
    setChartEmpty("age", true);
    try {
        const health = await fetchHealth();
        applyHealth(health);
        runIterations = health.run_iterations || 10;
        document.getElementById("sample-target").textContent = `n=${runIterations}`;
        updateRunButton();
        await initSidebar();
        await loadPresentationBackupPanel();
    } catch (_) {
        applyHealthError();
        setMeta("Backend API is unreachable. Start the application before running an experiment.", true);
    }
}

function bindInterfaceEvents() {
    document.getElementById("btn-run-mock").addEventListener("click", handleRun);
    document.getElementById("btn-health").addEventListener("click", toggleHealth);
    document.getElementById("health-close").addEventListener("click", toggleHealth);
    document.getElementById("btn-methodology").addEventListener("click", openMethodology);
    document.getElementById("btn-present").addEventListener("click", togglePresentation);
    document.getElementById("btn-menu").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
    document.getElementById("cinema-minimize").addEventListener("click", closeCinema);
    document.getElementById("cinema-reanalyze").addEventListener("click", handleReanalysis);
    document.getElementById("cinema-fallback-shortcut").addEventListener("click", handleReanalysis);
    document.getElementById("cinema-open-prepared").addEventListener("click", () => openPreparedExperiment(activePresentationBackup));
    document.getElementById("cinema-dismiss").addEventListener("click", closeCinema);
    document.getElementById("cinema-view-comparison").addEventListener("click", handleViewFullComparison);
    document.getElementById("btn-pin-experiment").addEventListener("click", pinCurrentExperiment);
    document.getElementById("btn-unpin-experiment").addEventListener("click", unpinExperiment);
    document.getElementById("btn-replay-experiment").addEventListener("click", replayVerifiedExperiment);
    document.getElementById("backup-select").addEventListener("change", selectPresentationBackup);
    document.getElementById("btn-activate-backup").addEventListener("click", activateSelectedBackup);
    document.getElementById("btn-verify-backup").addEventListener("click", verifySelectedBackup);
    document.getElementById("btn-open-backup-replay").addEventListener("click", () => openPreparedExperiment(selectedPresentationBackup));
    document.getElementById("btn-preflight").addEventListener("click", runBackupPreflight);
    document.getElementById("replay-pause").addEventListener("click", toggleReplayPause);
    document.getElementById("replay-restart").addEventListener("click", restartPreparedReplay);
    document.getElementById("replay-next").addEventListener("click", skipReplaySample);
    document.getElementById("replay-speed").addEventListener("change", (event) => { cinemaReplaySpeed = Number(event.target.value) || 1; });
    document.getElementById("replay-exit").addEventListener("click", closeCinema);
    document.querySelectorAll("[data-close-modal]").forEach((element) => element.addEventListener("click", closeMethodology));
    document.querySelectorAll("[data-close-lightbox]").forEach((element) => element.addEventListener("click", closeLightbox));
    document.addEventListener("keydown", handleKeyboard);
    document.addEventListener("fullscreenchange", handleFullscreenChange);
}

function applyHealth(health) {
    healthReady = health.status === "ready";
    fallbackVisionConfigured = Boolean(
        health.fallback_vision_configured && health.fallback_revision_storage_ready
    );
    const dot = document.getElementById("health-dot");
    dot.className = healthReady ? "ready" : "warning";
    document.getElementById("health-label").textContent = healthReady ? "System Configured" : "Configuration required";
    document.getElementById("health-status-text").textContent = healthReady ? "Configured · live quota checked during run" : "Configuration required";
    document.getElementById("health-api").textContent = healthReady ? "Configured" : "Configuration required";
    document.getElementById("health-provider").textContent = health.image_provider || "—";
    document.getElementById("health-image-model").textContent = health.image_model || "—";
    document.getElementById("health-vision-model").textContent = health.gemini_model || "—";
    document.getElementById("health-fallback-model").textContent = health.fallback_vision_model || "—";
    document.getElementById("health-fallback-ready").textContent = health.vision_test_simulation_active
        ? "TEST QUOTA SIMULATION ACTIVE"
        : fallbackVisionConfigured
            ? "Configured · quota checked live"
            : health.fallback_vision_configured
                ? "Migration required"
                : "Not configured";
    document.getElementById("health-queue").textContent = String(health.queue_size ?? 0);
    document.getElementById("health-openai").textContent = health.openai_configured ? "Yes" : "No";
    document.getElementById("health-gemini").textContent = health.gemini_configured ? "Yes" : "No";
    updateRunButton();
}

function applyHealthError() {
    healthReady = false;
    document.getElementById("health-dot").className = "error";
    document.getElementById("health-label").textContent = "API Unreachable";
    document.getElementById("health-status-text").textContent = "Unreachable";
    document.getElementById("health-api").textContent = "Unreachable";
    updateRunButton();
}

function toggleHealth() {
    const popover = document.getElementById("health-popover");
    popover.hidden = !popover.hidden;
    document.getElementById("btn-health").setAttribute("aria-expanded", String(!popover.hidden));
}

async function initSidebar() {
    const promptList = document.getElementById("prompt-list");
    const [categories, prompts] = await Promise.all([fetchCategories(), fetchPrompts()]);
    promptList.replaceChildren();
    categories.forEach((category) => {
        const categoryPrompts = prompts.filter((prompt) => prompt.category_id === category.id);
        if (!categoryPrompts.length) return;
        const title = document.createElement("div");
        title.className = "category-title";
        title.textContent = category.name;
        promptList.appendChild(title);
        categoryPrompts.forEach((prompt) => promptList.appendChild(createPromptButton(prompt)));
    });
}

function createPromptButton(prompt) {
    const button = document.createElement("button");
    button.className = "prompt-btn";
    button.type = "button";
    button.dataset.id = prompt.id;
    button.dataset.text = prompt.text;
    button.innerHTML = '<span class="prompt-icon" aria-hidden="true">›</span>';
    button.append(document.createTextNode(prompt.text));
    button.addEventListener("click", () => selectPrompt(button));
    return button;
}

async function selectPrompt(button) {
    document.querySelectorAll(".prompt-btn").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    selectedPromptId = button.dataset.id;
    selectedPromptText = button.dataset.text;
    document.getElementById("selected-prompt-label").textContent = selectedPromptText;
    document.getElementById("current-prompt-title").textContent = `“${selectedPromptText}”`;
    const sessionExperimentId = experimentForPrompt(selectedPromptId);
    document.getElementById("active-prompt-label").textContent = sessionExperimentId ? selectedPromptText : "None";
    document.getElementById("experiment-state").textContent = sessionExperimentId ? "Completed" : "Ready";
    setMeta(sessionExperimentId
        ? "Showing this session's experiment against the reference dataset."
        : "Ready for a new experiment. Historical runs are kept separate from this session.");
    document.getElementById("sidebar").classList.remove("open");
    updateRunButton();
    await loadDashboardData(selectedPromptId, sessionExperimentId);
}

function setMeta(message, isError = false) {
    const meta = document.getElementById("current-prompt-meta");
    meta.textContent = message;
    meta.classList.toggle("status-error", isError);
}

function updateRunButton(progress = null) {
    const button = document.getElementById("btn-run-mock");
    button.disabled = !selectedPromptId || runActive || !healthReady;
    button.querySelector("span").textContent = progress ? `Processing ${progress}` : `Run ${runIterations} Samples`;
    button.querySelector("small").textContent = runActive ? "Experiment in progress" : "Generate and analyze";
}

async function handleRun() {
    if (!selectedPromptId || runActive || !healthReady) return;
    const experimentPrompt = { id: selectedPromptId, text: selectedPromptText };
    sessionExperimentIds.delete(experimentPrompt.id);
    runActive = true;
    activeExperiment = { prompt: experimentPrompt, startedAt: Date.now(), status: "queued" };
    presentationContext = createPresentationContext({
        mode: "live",
        promptId: experimentPrompt.id,
        promptText: experimentPrompt.text,
    });
    document.getElementById("active-prompt-label").textContent = experimentPrompt.text;
    document.getElementById("experiment-state").textContent = "Queued";
    openCinema(experimentPrompt.text, runIterations);
    showLiveExperiment(experimentPrompt.text);
    setPipelineState("processing");
    startElapsedClock();
    updateRunButton(`0 / ${runIterations}`);
    try {
        const experiment = await runExperiment(experimentPrompt.id, runIterations);
        activeExperiment.id = experiment.id;
        presentationContext.experimentId = experiment.id;
        sessionExperimentIds.set(experimentPrompt.id, experiment.id);
        await pollUntilFinished(experiment.id, experimentPrompt);
    } catch (error) {
        const conflict = /active experiment|409/i.test(error.message || "");
        const message = conflict
            ? "An experiment for this prompt is already in progress."
            : "The experiment could not be started. Check system health and try again.";
        setLiveState({ ...(activeExperiment.lastStatus || { total: runIterations, completed: 0, succeeded: 0, failed: 0 }), status: "failed" }, message);
        setMeta(message, true);
        setPipelineState("failed");
        showCinemaStartFailure(message);
    } finally {
        runActive = false;
        stopElapsedClock();
        updateRunButton();
        if (selectedPromptId) await loadDashboardData(selectedPromptId, experimentForPrompt(selectedPromptId));
    }
}

async function pollUntilFinished(experimentId, prompt) {
    const deadline = Date.now() + 12 * 60 * 1000;
    let consecutiveErrors = 0;
    while (Date.now() < deadline) {
        let status;
        try {
            status = await fetchExperimentStatus(experimentId);
            consecutiveErrors = 0;
        } catch (_) {
            consecutiveErrors += 1;
            if (consecutiveErrors >= 3) throw new Error("Status endpoint unavailable");
            await delay(2000);
            continue;
        }
        activeExperiment.status = status.status;
        activeExperiment.lastStatus = status;
        setLiveState(status);
        updateCinema(status);
        refreshCinemaTrajectory(experimentId).catch(() => {});
        updateRunButton(`${status.completed} / ${status.total}`);
        document.getElementById("experiment-state").textContent = formatStatus(status.status);
        if (selectedPromptId === prompt.id && status.completed > 0) {
            await loadDashboardData(prompt.id, experimentId);
        }
        if (["completed", "failed"].includes(status.status)) {
            if (status.fallback_available) {
                setPipelineState("failed");
                setMeta("Generated images were preserved. Gemini validation is unavailable; OpenAI Vision re-analysis is ready.", true);
            } else if (status.succeeded > 0) {
                setPipelineState("completed");
                setMeta(`${status.succeeded} of ${status.total} samples are usable.${status.failed ? ` ${status.failed} failed and were excluded.` : ""}`);
            } else {
                setPipelineState("failed");
                setMeta("No usable samples were produced. Charts were not updated with failed results.", true);
            }
            return;
        }
        await delay(2000);
    }
    throw new Error("Experiment polling timed out");
}

async function handleReanalysis() {
    if (!activeExperiment?.id || runActive || !fallbackVisionConfigured) return;
    runActive = true;
    document.getElementById("cinema-fallback-shortcut").hidden = true;
    updateRunButton();
    try {
        const started = await reanalyzeExperiment(activeExperiment.id, "openai");
        openCinema(activeExperiment.prompt?.text || selectedPromptText, started.total, "reanalysis");
        showLiveExperiment(activeExperiment.prompt?.text || selectedPromptText);
        setPipelineState("processing");
        document.getElementById("experiment-state").textContent = "Reanalyzing";
        setCinemaStage("waiting", {
            kicker: "SECONDARY ANALYZER ACTIVE",
            title: "OpenAI GPT-4o mini Vision is revalidating every generated image",
            message: `Revalidating 0 / ${started.total} generated samples. Existing Gemini results remain staged separately until the full revision completes.`,
        });
        await pollReanalysis(activeExperiment.id, started.total);
    } catch (error) {
        setMeta(error.message || "OpenAI Vision re-analysis could not be started.", true);
        setCinemaStage("failed", {
            kicker: "RE-ANALYSIS COULD NOT START",
            title: "The saved images were left unchanged",
            message: "No image was regenerated and the active analysis revision was not changed.",
            reason: error.message || "The fallback service is unavailable.",
        });
    } finally {
        runActive = false;
        updateRunButton();
    }
}

async function pollReanalysis(experimentId, total) {
    const deadline = Date.now() + 12 * 60 * 1000;
    while (Date.now() < deadline) {
        const status = await fetchExperimentStatus(experimentId);
        activeExperiment.status = status.status;
        activeExperiment.lastStatus = status;
        setLiveState(status, `OpenAI Vision · ${status.completed} / ${status.total}`);
        updateCinema(status);
        refreshCinemaTrajectory(experimentId).catch(() => {});
        updateRunButton(`${status.completed} / ${status.total}`);
        document.getElementById("experiment-state").textContent = formatStatus(status.status);
        if (["completed", "failed"].includes(status.status)) {
            const experimentPromptId = activeExperiment?.prompt?.id || selectedPromptId;
            const dashboardIsOnExperimentPrompt = String(selectedPromptId || "") === String(experimentPromptId || "");
            const dashboardReady = status.status === "completed" && dashboardIsOnExperimentPrompt
                ? await refreshDashboardAfterReanalysis(experimentPromptId, experimentId, status.succeeded)
                : true;
            if (status.status === "completed") {
                setPipelineState("completed");
                setMeta(`Analysis provider switched: Gemini → OpenAI GPT-4o mini. Reason: ${formatFallbackReason(status.fallback_reason)}.`);
                if (!dashboardReady) {
                    setMeta("OpenAI analysis completed, but the dashboard could not refresh automatically. Select the occupation again to retry.", true);
                }
            } else {
                setPipelineState("failed");
                setMeta(status.safe_message || "The OpenAI analysis revision could not be activated.", true);
            }
            return;
        }
        await delay(2000);
    }
    throw new Error("OpenAI Vision re-analysis timed out")
}

async function refreshDashboardAfterReanalysis(promptId, experimentId, expectedValidated = 0) {
    const expected = Number(expectedValidated) || 0;
    for (let attempt = 0; attempt < 5; attempt += 1) {
        const loaded = await loadDashboardData(promptId, experimentId, { silent: true });
        const actual = Number(currentComparison?.validated_samples ?? currentComparison?.total_generations) || 0;
        if (loaded && String(currentComparison?.experiment_id || "") === String(experimentId) && actual >= expected) {
            return true;
        }
        await delay(300 + (attempt * 250));
    }
    return false;
}

function formatFallbackReason(reason) {
    if (!reason) return "Gemini unavailable";
    return reason.replace(/^gemini_/, "Gemini ").replaceAll("_", " ");
}

function showLiveExperiment(promptText) {
    document.getElementById("live-experiment").hidden = false;
    document.getElementById("process-theater").hidden = false;
    document.getElementById("live-prompt").textContent = `“${promptText}”`;
    setLiveState({ status: "processing", total: runIterations, completed: 0, succeeded: 0, failed: 0 });
}

function openCinema(promptText, total, mode = "live") {
    if (cinemaCloseTimer) window.clearTimeout(cinemaCloseTimer);
    if (cinemaPlaybackTimer) window.clearTimeout(cinemaPlaybackTimer);
    cinemaRenderedOrders = new Set();
    cinemaEventQueue = [];
    cinemaPlaying = false;
    cinemaFinishRequested = false;
    cinemaVisible = true;
    cinemaMode = mode;
    presentationMode = mode === "replay"
        ? currentReplayPayload?.analysis?.quality_policy === "composition-quality-v2"
            ? "prepared_replay"
            : "legacy_replay"
        : "live";
    cinemaReplayPaused = false;
    latestCinemaStatus = null;
    cinemaTrajectoryExperimentId = null;
    cinemaChartEvents = [];
    cinemaActiveSample = null;
    cinemaImageRequestId += 1;
    cinemaCanonicalState = createCinemaState(promptText, total, mode);
    const overlay = document.getElementById("loadingOverlay");
    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");
    document.getElementById("cinema-minimize").textContent = "Continue in background";
    document.getElementById("cinema-fallback-shortcut").hidden = true;
    document.getElementById("cinema-actions").hidden = true;
    document.getElementById("cinema-completion").hidden = true;
    document.getElementById("cinema-mode-title").textContent = presentationMode === "live" ? "Live Experiment" : "Prepared Replay";
    const replayQualityAssessed = presentationMode === "prepared_replay";
    const replayDisclosure = document.getElementById("cinema-replay-disclosure");
    replayDisclosure.hidden = false;
    replayDisclosure.textContent = presentationMode === "live"
        ? "Composition quality assessed"
        : replayQualityAssessed
            ? "Composition quality assessed"
            : "Legacy prepared replay — image quality not assessed";
    document.getElementById("cinema-replay-controls").hidden = mode !== "replay";
    document.getElementById("replay-pause").textContent = "Pause";
    document.getElementById("cinema-sample-result").hidden = false;
    initializeCinemaTimeline(cinemaCanonicalState.requested);
    renderCinemaState(cinemaCanonicalState);
    renderCinemaTrajectory(null);
    setCinemaStage("waiting", {
        kicker: mode === "replay" ? replayQualityAssessed ? "PREPARED VERIFIED EXPERIMENT" : "LEGACY PREPARED REPLAY" : mode === "reanalysis" ? "FALLBACK ANALYSIS" : "INITIALIZING",
        title: mode === "replay" ? "Preparing saved evidence replay" : mode === "reanalysis" ? "OpenAI Vision is analyzing the saved images" : "Waiting for the first completed sample",
        message: mode === "replay" ? "Saved results will be shown without provider requests." : "Generation and visual analysis are running in the background.",
        total: cinemaCanonicalState.requested,
    });
}

function createCinemaState(promptText, total, mode) {
    const requested = Math.max(1, Number(total) || runIterations);
    return {
        promptText: promptText || "—",
        mode,
        status: mode === "replay" ? "replay" : mode === "reanalysis" ? "reanalyzing" : "processing",
        requested,
        completed: 0,
        generated: 0,
        validated: 0,
        unverified: 0,
        failed: 0,
        excluded: 0,
        genderUsable: 0,
        genderUnclear: 0,
        ageUsable: 0,
        ageUnclear: 0,
        genderCounts: { Male: 0, Female: 0 },
        ageCounts: { "18-24": 0, "25-34": 0, "35-44": 0, "45-54": 0, "55+": 0 },
        analysisProvider: mode === "reanalysis" ? "openai" : mode === "replay" ? currentReplayPayload?.analysis?.provider : currentComparison?.analysis_provider || "gemini",
        analysisModel: mode === "reanalysis" ? "OpenAI Vision" : mode === "replay" ? currentReplayPayload?.analysis?.model : currentComparison?.analysis_model || "Gemini Vision",
        events: [],
    };
}

function deriveCinemaState(status = {}) {
    const previous = cinemaCanonicalState || createCinemaState(selectedPromptText, status.total, cinemaMode);
    const requested = Math.max(1, Number(status.total) || previous.requested || runIterations);
    const merged = new Map((previous.events || []).map((event, index) => [Number(event.sample_index || event.completed_order || index + 1), event]));
    (status.events || []).forEach((event, index) => {
        const key = Number(event.sample_index || event.completed_order || index + 1);
        merged.set(key, { ...merged.get(key), ...event, sample_index: key });
    });
    const events = [...merged.values()].sort((a, b) => Number(a.sample_index) - Number(b.sample_index));
    const completed = Math.min(requested, Math.max(events.length, Number(status.completed) || 0));
    const eventValidated = events.filter((event) => event.status === "success").length;
    const eventUnverified = events.filter((event) => event.status === "unverified").length;
    const validated = Math.min(completed, Number.isFinite(Number(status.succeeded)) ? Number(status.succeeded) : eventValidated);
    const unverified = Math.min(completed - validated, Number.isFinite(Number(status.unverified)) ? Number(status.unverified) : eventUnverified);
    const failed = Math.max(0, completed - validated - unverified);
    const generatedFromEvents = events.filter((event) => Boolean(event.image_reference) && event.status !== "failed").length;
    const generated = Math.min(requested, Number.isFinite(Number(status.generated)) ? Number(status.generated) : generatedFromEvents);
    const successfulEvents = events.filter((event) => event.status === "success");
    const genderCounts = { Male: 0, Female: 0 };
    const ageCounts = { "18-24": 0, "25-34": 0, "35-44": 0, "45-54": 0, "55+": 0 };
    successfulEvents.forEach((event) => {
        if (Number(event.detected_person_count) > 0 && Object.hasOwn(genderCounts, event.detected_gender)) genderCounts[event.detected_gender] += 1;
        if (Number(event.detected_person_count) > 0 && Object.hasOwn(ageCounts, event.detected_age_group)) ageCounts[event.detected_age_group] += 1;
    });
    const genderUsable = genderCounts.Male + genderCounts.Female;
    const ageUsable = Object.values(ageCounts).reduce((sum, value) => sum + value, 0);
    return {
        ...previous,
        status: status.status || previous.status,
        requested,
        completed,
        generated,
        validated,
        unverified,
        failed,
        excluded: unverified + failed,
        genderUsable,
        genderUnclear: Math.max(0, validated - genderUsable),
        ageUsable,
        ageUnclear: Math.max(0, validated - ageUsable),
        genderCounts,
        ageCounts,
        analysisProvider: status.analysis_provider || previous.analysisProvider,
        analysisModel: status.analysis_model || previous.analysisModel,
        events,
    };
}

function closeCinema() {
    cinemaVisible = false;
    const overlay = document.getElementById("loadingOverlay");
    overlay.classList.remove("active");
    overlay.setAttribute("aria-hidden", "true");
}

function createPresentationContext(overrides = {}) {
    return {
        mode: "live",
        experimentId: null,
        sourceExperimentId: null,
        promptId: null,
        promptText: null,
        analysisRevisionId: null,
        analyzerProvider: null,
        preparedSnapshot: null,
        ...overrides,
    };
}

function presentationTargetExperimentId(context = presentationContext) {
    return context.mode === "prepared_replay"
        ? context.sourceExperimentId
        : context.experimentId;
}

function syncDashboardPrompt(context) {
    selectedPromptId = context.promptId;
    selectedPromptText = context.promptText;
    document.querySelectorAll(".prompt-btn").forEach((button) => {
        button.classList.toggle("active", String(button.dataset.id) === String(context.promptId));
    });
    document.getElementById("selected-prompt-label").textContent = context.promptText || "—";
    document.getElementById("current-prompt-title").textContent = context.promptText ? `“${context.promptText}”` : "Choose a lens.";
    document.getElementById("active-prompt-label").textContent = context.promptText || "None";
    document.getElementById("experiment-state").textContent = "Completed";
    document.getElementById("sidebar").classList.remove("open");
    updateRunButton();
}

function stopCinemaPlayback() {
    if (cinemaCloseTimer) window.clearTimeout(cinemaCloseTimer);
    if (cinemaPlaybackTimer) window.clearTimeout(cinemaPlaybackTimer);
    cinemaCloseTimer = null;
    cinemaPlaybackTimer = null;
    cinemaPlaying = false;
    cinemaReplayPaused = true;
    cinemaFinishRequested = false;
    cinemaEventQueue = [];
}

function refreshVisibleDashboardCharts() {
    const refresh = () => Object.values(charts).forEach((chart) => {
        chart?.resize();
        chart?.update("none");
    });
    window.requestAnimationFrame(() => window.requestAnimationFrame(refresh));
}

function focusComparisonSection() {
    const heading = document.getElementById("comparison-heading");
    if (!heading) return;
    heading.scrollIntoView({ behavior: "smooth", block: "start" });
    heading.focus({ preventScroll: true });
}

async function handleViewFullComparison() {
    if (comparisonTransitionActive) return;
    const button = document.getElementById("cinema-view-comparison");
    const originalLabel = button.textContent;
    const context = { ...presentationContext };
    const experimentId = presentationTargetExperimentId(context);
    if (!experimentId || !context.promptId) {
        document.getElementById("cinema-completion-summary").textContent = "Full comparison is unavailable for this legacy replay.";
        document.getElementById("cinema-announcer").textContent = "Full comparison is unavailable for this legacy replay.";
        return;
    }

    comparisonTransitionActive = true;
    button.disabled = true;
    button.textContent = "Loading comparison…";
    try {
        let loaded = await loadDashboardData({
            promptId: context.promptId,
            experimentId,
            analysisRevisionId: context.analysisRevisionId,
            source: context.mode,
        });
        let usedPreparedSnapshot = false;
        if (!loaded && context.mode === "prepared_replay") {
            const snapshot = verifiedPreparedDashboardSnapshot(context, experimentId);
            if (snapshot) {
                applyDashboardData(snapshot.comparison, snapshot.results, experimentId);
                loaded = true;
                usedPreparedSnapshot = true;
            }
        }
        const exactExperimentLoaded = loaded
            && String(currentComparison?.experiment_id || "") === String(experimentId)
            && String(currentComparison?.prompt_id || "") === String(context.promptId);
        if (!exactExperimentLoaded) throw new Error("Recorded experiment scope did not match the dashboard response");

        presentationContext = createPresentationContext({
            ...context,
            experimentId,
            analysisRevisionId: currentComparison.analysis_revision ?? context.analysisRevisionId,
            analyzerProvider: currentComparison.analysis_provider ?? context.analyzerProvider,
        });
        syncDashboardPrompt(presentationContext);
        setMeta(usedPreparedSnapshot
            ? `Prepared verified experiment #${experimentId}.`
            : `${context.mode === "prepared_replay" ? "Viewing prepared experiment" : "Viewing live experiment"} #${experimentId}.`);
        stopCinemaPlayback();
        closeCinema();
        refreshVisibleDashboardCharts();
        window.requestAnimationFrame(focusComparisonSection);
    } catch (_) {
        const message = context.mode === "prepared_replay" && !verifiedPreparedDashboardSnapshot(context, experimentId)
            ? "Full comparison is unavailable for this legacy replay."
            : "The comparison could not be loaded. The recorded experiment is still available.";
        document.getElementById("cinema-completion-summary").textContent = message;
        document.getElementById("cinema-announcer").textContent = message;
    } finally {
        comparisonTransitionActive = false;
        button.disabled = false;
        button.textContent = originalLabel;
    }
}

function verifiedPreparedDashboardSnapshot(context, experimentId) {
    const dashboard = context.preparedSnapshot?.dashboard;
    if (!dashboard?.verified || !dashboard.comparison || !Array.isArray(dashboard.results)) return null;
    const snapshotExperimentId = dashboard.experiment_id || dashboard.comparison.experiment_id;
    const snapshotPromptId = dashboard.prompt_id || dashboard.comparison.prompt_id;
    if (String(snapshotExperimentId || "") !== String(experimentId)) return null;
    if (String(snapshotPromptId || "") !== String(context.promptId)) return null;
    return dashboard;
}

function updateCinema(status) {
    latestCinemaStatus = status;
    updateFallbackShortcut(status);
    cinemaCanonicalState = deriveCinemaState(status);
    renderCinemaState(cinemaCanonicalState);
    const total = cinemaCanonicalState.requested;
    (status.events || []).forEach((event, index) => {
        const order = Number(event.completed_order || index + 1);
        if (cinemaRenderedOrders.has(order)) return;
        cinemaRenderedOrders.add(order);
        cinemaEventQueue.push({ ...event, completed_order: order, total });
    });
    if (["completed", "failed"].includes(status.status)) cinemaFinishRequested = true;
    playNextCinemaEvent();
}

function renderCinemaState(state) {
    document.getElementById("cinema-running-prompt").textContent = `“${state.promptText}”`;
    document.getElementById("cinema-mode-badge").textContent = presentationMode === "prepared_replay"
        ? "PREPARED REPLAY — RECORDED RUN"
        : presentationMode === "legacy_replay"
            ? "LEGACY RECORDED RUN"
            : state.mode === "reanalysis" ? "FALLBACK ANALYSIS" : "LIVE";
    document.getElementById("cinema-analysis-provider").textContent = state.analysisProvider === "openai" ? "OpenAI Vision" : state.analysisProvider === "gemini" ? "Gemini Vision" : state.analysisModel || "Vision pending";
    setCinemaProgress(state);
    updateCinemaLiveCharts(state);
    updateCinemaTimeline(state);
}

function updateFallbackShortcut(status) {
    const shortcut = document.getElementById("cinema-fallback-shortcut");
    if (cinemaMode !== "live" || !status.fallback_available) {
        shortcut.hidden = true;
        return;
    }
    const finished = ["completed", "failed"].includes(status.status);
    shortcut.hidden = false;
    shortcut.disabled = !finished || !fallbackVisionConfigured;
    shortcut.textContent = !fallbackVisionConfigured
        ? "OpenAI fallback · migration required"
        : finished
            ? `Re-analyze ${status.generated || status.total} with OpenAI`
            : "OpenAI fallback ready after run";
    shortcut.title = shortcut.disabled && fallbackVisionConfigured
        ? "Re-analysis becomes available when generation finishes."
        : "Re-analyze every generated image with OpenAI Vision.";
}

function setCinemaProgress(state) {
    const safeTotal = Math.max(1, Number(state.requested) || runIterations);
    const percentage = `${Math.min(100, (Number(state.completed) / safeTotal) * 100)}%`;
    document.getElementById("cinema-counter").textContent = `${state.completed} / ${safeTotal} completed`;
    document.getElementById("cinema-progress-bar").style.setProperty("--cinema-progress", percentage);
    document.getElementById("cinema-generated").textContent = state.generated;
    document.getElementById("cinema-success").textContent = state.validated;
    document.getElementById("cinema-unverified").textContent = state.unverified;
    document.getElementById("cinema-failed").textContent = state.failed;
}

function playNextCinemaEvent() {
    if (cinemaPlaying || (cinemaMode === "replay" && cinemaReplayPaused)) return;
    const event = cinemaEventQueue.shift();
    if (!event) {
        if (cinemaFinishRequested) finishCinema();
        else setCinemaStage("waiting", {
            kicker: "GENERATION + VISION ACTIVE",
            title: "The next sample is crossing the validation gates",
            message: "Image workers are generating in parallel. Finished visuals are routed through vision analysis before they can enter the evidence set.",
        });
        return;
    }
    cinemaPlaying = true;
    const displayDuration = cinemaMode === "replay"
        ? Math.round(4500 / cinemaReplaySpeed)
        : cinemaEventQueue.length > 3 ? 900 : event.status === "success" ? 1500 : 1900;
    revealCinemaEvent(event, displayDuration);
    cinemaPlaybackTimer = window.setTimeout(() => {
        cinemaPlaying = false;
        playNextCinemaEvent();
    }, displayDuration);
}

function revealCinemaEvent(event, displayDuration) {
    if (cinemaMode === "replay") {
        const replayEvents = [...(cinemaCanonicalState?.events || []), event];
        cinemaCanonicalState = deriveCinemaState({
            status: "replay", total: currentReplayPayload?.counts?.requested || replayEvents.length,
            completed: replayEvents.length, generated: replayEvents.length,
            succeeded: replayEvents.filter((item) => item.status === "success").length,
            unverified: replayEvents.filter((item) => item.status === "unverified").length,
            events: replayEvents,
            analysis_provider: currentReplayPayload?.analysis?.provider,
            analysis_model: currentReplayPayload?.analysis?.model,
        });
        renderCinemaState(cinemaCanonicalState);
    }
    activateCinemaSample(event, displayDuration);
}

function activateCinemaSample(event, displayDuration = 0) {
    const sampleIndex = Number(event.sample_index || event.completed_order || 0);
    const sample = String(sampleIndex).padStart(2, "0");
    const imageSource = cinemaImageSource(event.image_reference);
    cinemaActiveSample = {
        id: event.id ?? event.result_id ?? null,
        resultId: event.result_id ?? event.id ?? null,
        index: sampleIndex,
        event,
        imageUrl: imageSource,
        status: event.status,
    };
    if (event.status === "success") {
        setCinemaStage("success", {
            imageSource,
            kicker: `${cinemaMode === "replay" ? "PREPARED REPLAY · " : cinemaMode === "reanalysis" ? "OPENAI VISION · " : ""}VALIDATED`,
            title: `Sample ${sample} validated`,
            message: "This sample is included in the validated evidence set.",
            sampleIndex,
            total: event.total || cinemaCanonicalState?.requested,
            resultGender: event.detected_gender || "Unclear",
            resultAge: event.detected_age_group || "Unclear",
            resultPeople: Number(event.detected_person_count) || 0,
            holdMs: displayDuration,
            holdLabel: "Validated sample",
            announce: `Sample ${sample} validated.`,
        });
    } else if (imageSource && event.phase === "analysis") {
        setCinemaStage("analysis-failed", {
            imageSource,
            kicker: "UNVERIFIED",
            title: "Analysis unavailable",
            message: "The image was saved as unverified evidence and excluded from statistics.",
            reason: event.reason || "The vision response could not be validated.",
            sampleIndex,
            total: event.total || cinemaCanonicalState?.requested,
            holdMs: displayDuration,
            holdLabel: "Unverified sample",
            badgeSymbol: "!",
            badgeText: "UNVERIFIED",
            announce: `Sample ${sample} is unverified.`,
        });
    } else {
        setCinemaStage("failed", {
            kicker: "FAILED / EXCLUDED",
            title: "Image generation failed",
            message: "This task was excluded. The remaining samples continue normally.",
            reason: event.reason || "The sample task could not be completed.",
            sampleIndex,
            total: event.total || cinemaCanonicalState?.requested,
            holdMs: displayDuration,
            holdLabel: "Failed sample",
            badgeSymbol: "×",
            badgeText: "FAILED",
            announce: `Sample ${sample} failed and was excluded.`,
        });
    }
    selectCinemaTimeline(sampleIndex);
}

function reviewCinemaSample(sampleIndex) {
    const event = (cinemaCanonicalState?.events || []).find((item) =>
        Number(item.sample_index || item.completed_order) === Number(sampleIndex)
    );
    if (!event) return;
    if (cinemaPlaybackTimer) window.clearTimeout(cinemaPlaybackTimer);
    cinemaPlaybackTimer = null;
    cinemaPlaying = false;
    if (cinemaMode === "replay") {
        cinemaReplayPaused = true;
        document.getElementById("replay-pause").textContent = "Play";
    }
    activateCinemaSample(event, 0);
}

function updateCinemaLiveCharts(state) {
    const genderCounts = state.genderCounts;
    const ageCounts = state.ageCounts;
    const genderTotal = state.genderUsable;
    const ageTotal = state.ageUsable;
    const setGender = (label, barId, valueId) => {
        const percentage = genderTotal ? (genderCounts[label] / genderTotal) * 100 : 0;
        document.getElementById(barId).style.width = `${percentage}%`;
        document.getElementById(valueId).textContent = genderTotal ? `${percentage.toFixed(0)}%` : "";
    };
    setGender("Male", "cinema-male-bar", "cinema-male-value");
    setGender("Female", "cinema-female-bar", "cinema-female-value");
    const ageIds = {
        "18-24": "cinema-age-18-24",
        "25-34": "cinema-age-25-34",
        "35-44": "cinema-age-35-44",
        "45-54": "cinema-age-45-54",
        "55+": "cinema-age-55",
    };
    const ageValueIds = {
        "18-24": "cinema-age-18-24-value",
        "25-34": "cinema-age-25-34-value",
        "35-44": "cinema-age-35-44-value",
        "45-54": "cinema-age-45-54-value",
        "55+": "cinema-age-55-value",
    };
    Object.entries(ageCounts).forEach(([label, count]) => {
        const percentage = ageTotal ? (count / ageTotal) * 100 : 0;
        document.getElementById(ageIds[label]).style.height = count ? `${Math.max(percentage, 8)}%` : "0%";
        document.getElementById(ageIds[label]).title = ageTotal ? `${label}: ${percentage.toFixed(0)}%` : `${label}: no data`;
        document.getElementById(ageValueIds[label]).textContent = count ? `${percentage.toFixed(0)}%` : "";
    });
    document.getElementById("cinema-live-n").textContent = `${state.validated} validated`;
    document.getElementById("cinema-live-excluded").textContent = `${state.excluded} excluded`;
    document.getElementById("cinema-gender-n").textContent = `Usable n=${genderTotal}`;
    document.getElementById("cinema-age-n").textContent = `Usable n=${ageTotal}`;
    document.getElementById("cinema-gender-detail").textContent = `Usable n=${genderTotal} · Unclear=${state.genderUnclear}`;
    document.getElementById("cinema-age-detail").textContent = `Usable n=${ageTotal} · Unclear=${state.ageUnclear}`;
    document.getElementById("cinema-gender-empty").hidden = genderTotal > 0;
    document.getElementById("cinema-age-empty").hidden = ageTotal > 0;
    document.getElementById("cinema-live-note").textContent = state.validated
        ? `Validated analyses: ${state.validated} · unverified and failed samples are excluded from distributions.`
        : state.excluded
            ? `${state.excluded} completed sample${state.excluded === 1 ? " is" : "s are"} excluded; no validated distribution yet.`
            : "Waiting for validated classifications.";
}

async function refreshCinemaTrajectory(experimentId) {
    if (!cinemaVisible || cinemaMode === "replay") return;
    cinemaTrajectoryExperimentId = String(experimentId);
    const trajectory = await fetchExperimentTrajectory(experimentId);
    if (cinemaTrajectoryExperimentId !== String(experimentId)) return;
    renderCinemaTrajectory(trajectory);
}

function renderCinemaTrajectory(trajectory) {
    const canvas = document.getElementById("cinema-trajectory-canvas");
    const label = document.getElementById("cinema-trajectory-label");
    if (!canvas || !label) return;
    const width = Math.max(260, Math.round(canvas.clientWidth || 520));
    const height = Math.max(70, Math.round(canvas.clientHeight || 120));
    const scale = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(width * scale) || canvas.height !== Math.round(height * scale)) {
        canvas.width = Math.round(width * scale);
        canvas.height = Math.round(height * scale);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const points = trajectory?.points || [];
    const padding = { left: 18, right: 10, top: 8, bottom: 15 };
    const graphWidth = width - padding.left - padding.right;
    const graphHeight = height - padding.top - padding.bottom;
    ctx.strokeStyle = "rgba(255,255,255,.08)";
    ctx.lineWidth = 1;
    [0, 50, 100].forEach(value => {
        const y = padding.top + graphHeight * (1 - value / 100);
        ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    });
    const reference = trajectory?.reference?.values?.Female;
    if (Number.isFinite(reference)) {
        const y = padding.top + graphHeight * (1 - reference);
        ctx.save(); ctx.setLineDash([5, 5]); ctx.strokeStyle = "rgba(94,234,212,.72)";
        ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke(); ctx.restore();
    }
    const usable = points.filter(point => Number.isFinite(point.shares?.Female));
    if (!usable.length) {
        label.textContent = "Waiting for validated n";
        return;
    }
    const maxN = Math.max(2, points[points.length - 1].n);
    const coords = usable.map(point => ({
        x: padding.left + ((point.n - 1) / (maxN - 1)) * graphWidth,
        y: padding.top + graphHeight * (1 - point.shares.Female),
    }));
    ctx.strokeStyle = "#a78bfa"; ctx.lineWidth = 2.5; ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath(); coords.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y)); ctx.stroke();
    const last = coords[coords.length - 1]; ctx.fillStyle = "#5eead4"; ctx.beginPath(); ctx.arc(last.x, last.y, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "rgba(195,203,216,.78)"; ctx.font = "9px DM Mono, monospace";
    ctx.fillText("0", 2, padding.top + graphHeight + 3); ctx.fillText("100", 0, padding.top + 4);
    const finalPoint = points[points.length - 1];
    const female = finalPoint.shares?.Female;
    label.textContent = `${Number.isFinite(female) ? `${(female * 100).toFixed(0)}% female` : "No classified value"} · n=${finalPoint.n} · unclear=${finalPoint.unclear_count}${finalPoint.n < 10 ? " · demo-scale" : ""}`;
}

function setCinemaStage(state, content) {
    const visual = document.getElementById("cinema-visual");
    const image = document.getElementById("cinema-image");
    const placeholder = document.getElementById("cinema-image-placeholder");
    const reason = document.getElementById("cinema-reason");
    const hold = document.getElementById("cinema-hold");
    const holdBar = document.getElementById("cinema-hold-bar");
    const failureMark = document.getElementById("cinema-failure-mark");
    document.getElementById("cinema-actions").hidden = true;
    document.getElementById("cinema-completion").hidden = true;
    document.getElementById("cinema-sample-result").hidden = false;
    visual.className = "cinema-visual waiting";
    void visual.offsetWidth;
    visual.className = `cinema-visual ${state}`;
    image.onload = null;
    image.onerror = null;
    image.hidden = true;
    image.setAttribute("aria-hidden", "true");
    image.alt = "";
    delete image.dataset.source;
    delete image.dataset.sampleIndex;
    placeholder.hidden = true;
    const requestId = ++cinemaImageRequestId;
    if (content.imageSource) {
        const expectedSource = normalizeCinemaSource(content.imageSource);
        image.onload = () => {
            if (requestId !== cinemaImageRequestId || normalizeCinemaSource(image.currentSrc || image.src) !== expectedSource) return;
            visual.classList.add("media-ready");
            image.hidden = false;
            image.setAttribute("aria-hidden", "false");
            image.alt = `Generated sample ${String(content.sampleIndex || "").padStart(2, "0")} — ${state === "success" ? "validated" : "unverified"}`;
            image.dataset.source = expectedSource;
            image.dataset.sampleIndex = String(content.sampleIndex || "");
            image.dataset.resultId = String(cinemaActiveSample?.resultId ?? "");
        };
        image.src = content.imageSource;
    } else {
        image.removeAttribute("src");
    }
    image.onerror = () => {
        if (requestId !== cinemaImageRequestId) return;
        image.hidden = true;
        image.setAttribute("aria-hidden", "true");
        image.alt = "";
        image.removeAttribute("src");
        placeholder.hidden = false;
        if (visual.classList.contains("success")) visual.className = "cinema-visual waiting";
    };
    document.getElementById("cinema-kicker").textContent = content.kicker;
    document.getElementById("cinema-title").textContent = content.title;
    document.getElementById("loadingText").textContent = content.message;
    document.getElementById("cinema-active-sample").textContent = content.sampleIndex
        ? `SAMPLE ${String(content.sampleIndex).padStart(2, "0")} / ${String(content.total || cinemaCanonicalState?.requested || runIterations).padStart(2, "0")}`
        : `SAMPLE — / ${String(content.total || cinemaCanonicalState?.requested || runIterations).padStart(2, "0")}`;
    document.getElementById("cinema-result-gender").textContent = content.resultGender ?? "—";
    document.getElementById("cinema-result-age").textContent = content.resultAge ?? "—";
    document.getElementById("cinema-result-people").textContent = content.resultPeople ?? "—";
    failureMark.querySelector("span").textContent = content.badgeSymbol || "×";
    failureMark.querySelector("b").textContent = content.badgeText || "FAILED";
    failureMark.hidden = !["failed", "analysis-failed"].includes(state);
    failureMark.setAttribute("aria-hidden", String(failureMark.hidden));
    reason.hidden = !content.reason;
    reason.textContent = content.reason || "";
    hold.hidden = !content.holdMs;
    if (content.holdMs) {
        document.getElementById("cinema-hold-label").textContent = content.holdLabel || "Frame held for review";
        holdBar.style.animation = "none";
        void holdBar.offsetWidth;
        holdBar.style.animation = `cinemaHold ${content.holdMs}ms linear forwards`;
    }
    if (content.announce) document.getElementById("cinema-announcer").textContent = content.announce;
}

function normalizeCinemaSource(source) {
    try {
        const url = new URL(source, window.location.href);
        url.search = "";
        url.hash = "";
        return decodeURIComponent(url.pathname);
    } catch (_) {
        return String(source || "").split(/[?#]/)[0];
    }
}

function initializeCinemaTimeline(total) {
    const timeline = document.getElementById("cinema-timeline");
    timeline.replaceChildren();
    for (let index = 1; index <= total; index += 1) {
        const item = document.createElement("div");
        item.className = "timeline-item pending";
        item.dataset.sampleIndex = String(index);
        item.dataset.resultId = "";
        item.dataset.status = "pending";
        item.setAttribute("aria-label", `Sample ${String(index).padStart(2, "0")}: pending`);
        item.setAttribute("role", "button");
        item.tabIndex = 0;
        item.addEventListener("click", () => reviewCinemaSample(index));
        item.addEventListener("keydown", (keyboardEvent) => {
            if (!["Enter", " "].includes(keyboardEvent.key)) return;
            keyboardEvent.preventDefault();
            reviewCinemaSample(index);
        });
        const label = document.createElement("span");
        label.className = "timeline-number";
        label.textContent = String(index).padStart(2, "0");
        const icon = document.createElement("b");
        icon.className = "timeline-status-icon";
        icon.textContent = "·";
        item.append(label, icon);
        timeline.append(item);
    }
}

function updateCinemaTimeline(state) {
    const byIndex = new Map(state.events.map((event) => [Number(event.sample_index), event]));
    document.querySelectorAll("#cinema-timeline .timeline-item").forEach((item) => {
        const index = Number(item.dataset.sampleIndex);
        const event = byIndex.get(index);
        const isNext = !event && index === state.completed + 1 && ["processing", "reanalyzing"].includes(state.status);
        const status = event?.status === "success" ? "validated" : event?.status === "unverified" ? "unverified" : event?.status === "failed" ? "failed" : isNext ? "generating" : "pending";
        if (item.dataset.status !== status) {
            item.dataset.status = status;
            item.className = `timeline-item ${status}`;
            item.querySelector(".timeline-status-icon").textContent = ({ validated: "✓", unverified: "!", failed: "×", generating: "…", pending: "·" })[status];
        }
        const label = `Sample ${String(index).padStart(2, "0")}: ${status}`;
        item.title = label;
        item.setAttribute("aria-label", label);
        const imageSource = cinemaImageSource(event?.image_reference);
        item.dataset.resultId = String(event?.result_id ?? event?.id ?? "");
        let image = item.querySelector("img");
        if (imageSource && (!image || image.dataset.source !== imageSource)) {
            if (!image) {
                image = document.createElement("img");
                image.addEventListener("error", () => image.remove(), { once: true });
                item.prepend(image);
            }
            image.dataset.source = imageSource;
            image.src = imageSource;
            image.alt = `Generated sample ${String(index).padStart(2, "0")}, ${status}`;
        }
    });
}

function selectCinemaTimeline(sampleIndex) {
    document.querySelectorAll("#cinema-timeline .timeline-item").forEach((item) => {
        item.classList.toggle("selected", Number(item.dataset.sampleIndex) === Number(sampleIndex));
    });
}

function finishCinema() {
    cinemaFinishRequested = false;
    if (cinemaMode === "live" && latestCinemaStatus?.fallback_available) {
        showFallbackChoice(latestCinemaStatus);
        return;
    }
    const state = cinemaCanonicalState || createCinemaState(selectedPromptText, runIterations, cinemaMode);
    const finalEvent = [...state.events].reverse().find((event) => event.status === "success" && event.image_reference)
        || [...state.events].reverse().find((event) => event.status === "unverified" && event.image_reference);
    if (finalEvent) {
        const finalIsValidated = finalEvent.status === "success";
        setCinemaStage(finalIsValidated ? "success" : "analysis-failed", {
            imageSource: cinemaImageSource(finalEvent.image_reference),
            kicker: finalIsValidated ? "FINAL VALIDATED SAMPLE" : "FINAL UNVERIFIED IMAGE",
            title: "Experiment complete",
            message: "The final distribution is ready for review.",
            sampleIndex: finalEvent.sample_index,
            total: state.requested,
            resultGender: finalEvent.detected_gender || "Unclear",
            resultAge: finalEvent.detected_age_group || "Unclear",
            resultPeople: Number(finalEvent.detected_person_count) || 0,
            badgeSymbol: "!",
            badgeText: "UNVERIFIED",
        });
    }
    document.getElementById("cinema-sample-result").hidden = true;
    document.getElementById("cinema-completion").hidden = false;
    document.getElementById("cinema-reason").hidden = true;
    document.getElementById("cinema-hold").hidden = true;
    document.getElementById("cinema-actions").hidden = true;
    const modePrefix = cinemaMode === "replay" ? "Prepared verified experiment · " : "";
    document.getElementById("cinema-completion-counts").textContent = `${modePrefix}${state.requested} requested · ${state.generated} generated · ${state.validated} validated · ${state.unverified} unverified · ${state.failed} failed`;
    document.getElementById("cinema-completion-summary").textContent = summarizeCinemaOutcome(state);
    document.getElementById("cinema-final-yield").textContent = `${state.validated} / ${state.requested}`;
    document.getElementById("cinema-final-provider").textContent = state.analysisProvider === "openai" ? "OpenAI Vision" : state.analysisProvider === "gemini" ? "Gemini Vision" : state.analysisModel || "Vision unavailable";
    document.getElementById("cinema-final-usable").textContent = `Gender ${state.genderUsable} · Age ${state.ageUsable}`;
    document.getElementById("cinema-minimize").textContent = "View results";
    document.getElementById("cinema-announcer").textContent = `Experiment complete. ${state.validated} of ${state.requested} samples validated.`;
    selectCinemaTimeline(0);
}

function summarizeCinemaOutcome(state) {
    if (!state.validated) return "No sample produced a validated analysis; no representation comparison is reported.";
    const sameExperiment = currentComparison && (!activeExperiment?.id || String(currentComparison.experiment_id) === String(activeExperiment.id));
    if (sameExperiment && state.genderUsable > 0) {
        const differences = Object.entries(currentComparison.gender_comparison || {})
            .map(([label, values]) => ({ label, difference: Number(values.difference) }))
            .filter((item) => ["Male", "Female"].includes(item.label) && Number.isFinite(item.difference))
            .sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference));
        const strongest = differences[0];
        if (strongest && Math.abs(strongest.difference) >= .5) {
            return `The validated sample currently ${strongest.difference > 0 ? "over-represents" : "under-represents"} ${strongest.label.toLowerCase()} presentation compared with the reference distribution.`;
        }
        if (strongest) return "The validated gender presentation is currently close to the reference distribution.";
    }
    if (state.genderUsable > 0) {
        const dominant = state.genderCounts.Male === state.genderCounts.Female ? null : state.genderCounts.Male > state.genderCounts.Female ? "male" : "female";
        return dominant ? `${dominant[0].toUpperCase()}${dominant.slice(1)} presentation is currently the most frequent usable gender classification.` : "Male and female presentation are currently balanced among usable classifications.";
    }
    return "Validated samples are available, but no usable gender presentation classification was produced.";
}

function showFallbackChoice(status) {
    setCinemaStage("analysis-failed", {
        kicker: "GEMINI VISION IS CURRENTLY UNAVAILABLE",
        title: "The generated images are safe",
        message: "Validation could not be completed, so these images were not included in the analysis.",
        reason: status.safe_message || "Gemini quota or service capacity is currently unavailable.",
    });
    const actions = document.getElementById("cinema-actions");
    actions.hidden = false;
    document.getElementById("cinema-reanalyze").disabled = !fallbackVisionConfigured || !activeExperiment?.id || !(status.generated > 0);
    document.getElementById("cinema-open-prepared").disabled = !activePresentationBackup;
    document.getElementById("cinema-minimize").textContent = "Keep generated images";
}

function showCinemaStartFailure(message) {
    cinemaFinishRequested = false;
    cinemaEventQueue = [];
    setCinemaStage("failed", {
        kicker: "EXPERIMENT COULD NOT START",
        title: "The lens stayed closed",
        message: "No sample task was charged or added to this run.",
        reason: message,
    });
    if (cinemaVisible) cinemaCloseTimer = window.setTimeout(closeCinema, 3200);
}

function cinemaImageSource(reference) {
    if (!reference) return "";
    return reference.startsWith("http") ? reference : `/assets/generations/${String(reference).split("/").map(encodeURIComponent).join("/")}`;
}

function setLiveState(status, overrideMessage = null) {
    const total = status.total || runIterations;
    const completed = Math.min(status.completed || 0, total);
    const succeeded = Math.min(status.succeeded || 0, completed);
    const failed = Math.min((status.failed || 0) + (status.unverified || 0), completed - succeeded);
    document.getElementById("live-progress").textContent = `${completed} / ${total}`;
    document.getElementById("live-success").textContent = succeeded;
    document.getElementById("live-failed").textContent = failed;
    document.getElementById("live-message").textContent = overrideMessage || formatStatus(status.status);
    renderSampleStrip(total, succeeded, failed, completed, status.status);
    updateProcessTheater({ ...status, total, completed, succeeded, failed });
}

function updateProcessTheater(status) {
    const title = document.getElementById("process-title");
    const description = document.getElementById("process-description");
    const events = document.getElementById("process-events");
    const breakdown = status.failure_breakdown || { generation: 0, analysis: 0, worker: 0 };
    const totalFailures = (breakdown.generation || 0) + (breakdown.analysis || 0) + (breakdown.worker || 0);
    if (status.status === "completed") {
        title.textContent = status.succeeded ? "Experiment evidence is ready" : "Experiment finished without usable evidence";
        description.textContent = status.succeeded
            ? "Validated results are now compared with the reference distribution."
            : "No result completed both image generation and vision analysis.";
    } else if (status.status === "failed") {
        title.textContent = "The pipeline could not produce usable evidence";
        description.textContent = "Failed tasks were isolated and excluded from the research charts.";
    } else if (status.completed > 0) {
        title.textContent = "Generation and vision analysis are running in parallel";
        description.textContent = "Workers generate independent images; completed images are routed to Gemini Vision and validated before storage.";
    } else {
        title.textContent = "Independent sample tasks are entering the queue";
        description.textContent = "Each worker will generate one image, analyze visible presentation, then store only a validated result.";
    }
    const messages = [
        { text: `${status.completed} of ${status.total} tasks completed`, type: "" },
        { text: `${status.succeeded} samples passed generation and vision validation`, type: "success" },
    ];
    if (status.failed) messages.push({ text: `${status.failed} tasks were excluded from charts`, type: "failed" });
    events.replaceChildren(...messages.map((item) => {
        const line = document.createElement("div");
        line.className = `process-event ${item.type}`.trim();
        line.textContent = item.text;
        return line;
    }));
    document.getElementById("failure-breakdown").hidden = totalFailures === 0;
    document.getElementById("failure-generation").textContent = breakdown.generation || 0;
    document.getElementById("failure-analysis").textContent = breakdown.analysis || 0;
    document.getElementById("failure-worker").textContent = breakdown.worker || 0;
}

function renderSampleStrip(total, succeeded, failed, completed, status) {
    const strip = document.getElementById("sample-strip");
    strip.replaceChildren();
    for (let index = 0; index < total; index += 1) {
        const sample = document.createElement("span");
        sample.className = "sample-dot";
        if (index < succeeded) sample.classList.add("success");
        else if (index < succeeded + failed) sample.classList.add("failed");
        else if (index === completed && status === "processing") sample.classList.add("processing");
        strip.appendChild(sample);
    }
    strip.setAttribute("aria-label", `${succeeded} successful, ${failed} failed, ${Math.max(0, total - completed)} remaining`);
}

function startElapsedClock() {
    stopElapsedClock();
    const update = () => {
        const elapsed = Math.floor((Date.now() - activeExperiment.startedAt) / 1000);
        const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const seconds = String(elapsed % 60).padStart(2, "0");
        document.getElementById("live-elapsed").textContent = `${minutes}:${seconds}`;
    };
    update();
    elapsedTimer = window.setInterval(update, 1000);
}

function stopElapsedClock() {
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    elapsedTimer = null;
}

function formatStatus(status) {
    return ({ processing: "Processing", reanalyzing: "Reanalyzing", completed: "Completed", failed: "Failed", queued: "Queued" })[status] || "Ready";
}

function setPipelineState(state) {
    const pipeline = document.querySelector(".pipeline");
    pipeline.className = `pipeline ${state || ""}`.trim();
}

async function loadDashboardData(promptOrRequest, experimentId = null, options = {}) {
    const request = typeof promptOrRequest === "object" && promptOrRequest !== null
        ? { ...promptOrRequest }
        : { promptId: promptOrRequest, experimentId, ...options };
    const promptId = request.promptId;
    experimentId = request.experimentId || null;
    try {
        const [rawData, results] = experimentId
            ? await Promise.all([
                fetchExperimentComparison(experimentId),
                fetchExperimentResults(experimentId),
            ])
            : [await fetchComparison(promptId), []];
        const data = experimentId ? rawData : freshSessionComparison(rawData);
        applyDashboardData(data, results, experimentId);
        return true;
    } catch (_) {
        if (!request.silent) setMeta("Dashboard data could not be loaded. Existing results remain unchanged.", true);
        return false;
    }
}

function applyDashboardData(data, results, experimentId) {
    currentComparison = experimentId ? data : null;
    currentExperimentResults = experimentId ? results : [];
    updateStats(data);
    updateCharts(data);
    updateObservation(data);
    renderGallery((results || [])
        .filter((result) => result.generation_status === "success" && result.analysis_status === "success")
        .map((result) => result.image_reference));
    updateProviderDisplay(data);
    updatePreparedExperiment(data, results || [], experimentId);
}

function updateProviderDisplay(data) {
    const provider = data.analysis_provider === "openai" ? "OpenAI" : data.analysis_provider === "gemini" ? "Gemini" : "Vision pending";
    const model = data.analysis_model || "—";
    document.getElementById("active-model-label").textContent = `GPT Image → ${provider} ${model === "—" ? "" : model}`.trim();
}

function updatePreparedExperiment(data, results, experimentId) {
    const panel = document.getElementById("prepared-experiment");
    if (!experimentId) {
        panel.hidden = true;
        return;
    }
    const validated = Number(data.validated_samples ?? data.total_generations) || 0;
    const unverified = Number(data.unverified_samples) || 0;
    const failed = Number(data.failed_samples) || 0;
    const isBackedUp = presentationBackups.some((item) => String(item.source_experiment_id) === String(experimentId));
    panel.hidden = false;
    document.getElementById("prepared-kicker").textContent = isBackedUp ? "PRESENTATION BACKUP SAVED" : data.fallback_reason ? "SECONDARY ANALYZER RESULT" : "CURRENT VERIFIED EXPERIMENT";
    document.getElementById("prepared-title").textContent = data.prompt_text || selectedPromptText || "Saved experiment";
    document.getElementById("prepared-summary").textContent = `${data.requested_samples || results.length} requested · ${validated} validated · ${unverified} unverified${failed ? ` · ${failed} generation failed` : ""}${data.fallback_reason ? " · Gemini → OpenAI fallback" : ""}`;
    document.getElementById("prepared-generation").textContent = "gpt-image-2";
    document.getElementById("prepared-analysis").textContent = data.analysis_model || "Analysis pending";
    const pinButton = document.getElementById("btn-pin-experiment");
    pinButton.hidden = isBackedUp;
    pinButton.disabled = validated < 1;
    pinButton.textContent = validated < 1 ? "Requires a validated result" : "Save as Presentation Backup";
    document.getElementById("btn-unpin-experiment").hidden = true;
    const replayButton = document.getElementById("btn-replay-experiment");
    replayButton.disabled = validated < 1 || !results.length;
    replayButton.textContent = isBackedUp ? "Open Prepared Replay" : "Preview Current Results";
}

function freshSessionComparison(data) {
    const fresh = JSON.parse(JSON.stringify(data));
    fresh.total_generations = 0;
    fresh.valid_person_analyses = 0;
    fresh.valid_gender_analyses = 0;
    fresh.valid_age_analyses = 0;
    fresh.failed_generations = 0;
    fresh.analysis_provider = null;
    fresh.analysis_model = null;
    fresh.analysis_revision = null;
    fresh.fallback_reason = null;
    ["gender_comparison", "age_group_comparison"].forEach((dimension) => {
        Object.values(fresh[dimension] || {}).forEach((item) => {
            item.ai_percentage = 0;
            item.difference = 0;
        });
    });
    return fresh;
}

function updateStats(data) {
    const successful = Number(data.total_generations) || 0;
    const failed = Number(data.failed_generations) || 0;
    const valid = Number(data.valid_person_analyses) || 0;
    const genderValid = Number(data.valid_gender_analyses) || 0;
    const ageValid = Number(data.valid_age_analyses) || 0;
    const attempted = successful + failed;
    document.getElementById("stat-total").textContent = successful;
    document.getElementById("stat-valid").textContent = valid;
    document.getElementById("stat-source").textContent = data.source || "—";
    document.getElementById("usable-label").textContent = attempted ? `${successful} of ${attempted} validated samples` : "No experiment in this session";
    document.getElementById("stat-rate").textContent = attempted ? `${((successful / attempted) * 100).toFixed(1)}%` : "—";
    document.getElementById("rate-label").textContent = attempted
        ? failed ? `${failed} excluded sample${failed === 1 ? "" : "s"}` : "All attempted samples validated"
        : "Run an experiment to calculate";
    const genderHasData = genderValid > 0 && hasAiValues(data.gender_comparison);
    const gap = genderHasData ? largestDifference(data.gender_comparison) : null;
    const deviation = gap ? Math.abs(gap.difference) : null;
    document.getElementById("stat-gap").textContent = deviation === null ? "—" : `${deviation.toFixed(1)}%`;
    document.getElementById("gender-deviation-card").classList.toggle("deviation-alert", deviation !== null && deviation > 0.05);
    document.getElementById("gap-label").textContent = gap
        ? deviation <= 0.05
            ? "Generated sample matches the reference"
            : `${gap.label} representation deviates · n=${genderValid}`
        : "Not enough validated gender data";
    document.getElementById("gender-sample-label").textContent = `n=${genderValid} validated gender classifications`;
    document.getElementById("age-sample-label").textContent = `n=${ageValid} validated age classifications`;
}

function largestDifference(comparison = {}) {
    return Object.entries(comparison).map(([label, values]) => ({ label, ...values }))
        .filter((item) => Number.isFinite(Number(item.difference)))
        .sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference))[0] || null;
}

function updateCharts(data) {
    const successful = Number(data.total_generations) || 0;
    const genderValid = Number(data.valid_gender_analyses) || 0;
    const ageValid = Number(data.valid_age_analyses) || 0;
    const genderHasData = successful > 0 && genderValid > 0 && hasAiValues(data.gender_comparison);
    const ageHasData = successful > 0 && ageValid > 0 && hasAiValues(data.age_group_comparison);
    setChartEmpty("gender", !genderHasData);
    setChartEmpty("age", !ageHasData);
    document.getElementById("gender-signal").textContent = genderHasData ? signalLabel(data.gender_comparison) : "No data";
    document.getElementById("age-signal").textContent = ageHasData ? signalLabel(data.age_group_comparison) : "No data";
    if (genderHasData) upsertChart("gender", data.gender_comparison);
    else destroyChart("gender");
    if (ageHasData) upsertChart("age", data.age_group_comparison);
    else destroyChart("age");
}

function hasAiValues(comparison = {}) {
    return Object.values(comparison).some((item) => Number.isFinite(Number(item.ai_percentage)) && Number(item.ai_percentage) > 0);
}

function setChartEmpty(type, isEmpty) {
    document.getElementById(`${type}-empty`).hidden = !isEmpty;
    document.getElementById(`${type}Chart`).hidden = isEmpty;
}

function destroyChart(type) {
    if (charts[type]) charts[type].destroy();
    charts[type] = null;
}

function upsertChart(type, comparison) {
    const labels = Object.keys(comparison);
    if (type === "age") {
        const order = ["18-24", "25-34", "35-44", "45-54", "55+"];
        labels.sort((a, b) => order.indexOf(a) - order.indexOf(b));
    }
    const canvas = document.getElementById(`${type}Chart`);
    const context = canvas.getContext("2d");
    const referenceGradient = context.createLinearGradient(0, 0, type === "gender" ? 500 : 0, type === "gender" ? 0 : 280);
    referenceGradient.addColorStop(0, "rgba(94,234,212,.92)");
    referenceGradient.addColorStop(1, "rgba(20,184,166,.36)");
    const aiGradient = context.createLinearGradient(0, 0, type === "gender" ? 500 : 0, type === "gender" ? 0 : 280);
    aiGradient.addColorStop(0, "rgba(196,181,253,.96)");
    aiGradient.addColorStop(1, "rgba(109,40,217,.48)");
    const datasets = [
        { label: "Reference", data: labels.map((label) => comparison[label].real_world_percentage), backgroundColor: referenceGradient, borderColor: "rgba(94,234,212,.8)", borderWidth: 1, borderRadius: 7, barPercentage: .7, categoryPercentage: .72 },
        { label: "AI generated", data: labels.map((label) => comparison[label].ai_percentage), backgroundColor: aiGradient, borderColor: "rgba(196,181,253,.8)", borderWidth: 1, borderRadius: 7, barPercentage: .7, categoryPercentage: .72 },
    ];
    if (charts[type]) {
        charts[type].data.labels = labels;
        charts[type].data.datasets = datasets;
        charts[type].update("none");
        return;
    }
    charts[type] = new Chart(canvas, {
        type: "bar", data: { labels, datasets }, plugins: [chartValueLabels],
        options: {
            indexAxis: type === "gender" ? "y" : "x",
            responsive: true, maintainAspectRatio: false, animation: { duration: 650, easing: "easeOutQuart" },
            layout: { padding: type === "gender" ? { right: 42, top: 8, bottom: 8 } : { top: 20, right: 8 } },
            scales: type === "gender"
                ? { x: { min: 0, max: 100, ticks: { callback: (value) => `${value}%` }, grid: { color: "rgba(148,163,184,.09)" } }, y: { grid: { display: false }, ticks: { color: "#d7dbea", font: { family: "DM Mono", size: 10 } } } }
                : { y: { min: 0, max: 100, ticks: { callback: (value) => `${value}%` }, grid: { color: "rgba(148,163,184,.09)" } }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: false, color: "#aeb5c4", font: { family: "DM Mono", size: 9 } } } },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { afterBody: (items) => {
                    const index = items[0].dataIndex;
                    const reference = Number(datasets[0].data[index]);
                    const ai = Number(datasets[1].data[index]);
                    const difference = ai - reference;
                    return [`Reference: ${reference.toFixed(1)}%`, `AI generated: ${ai.toFixed(1)}%`, `Difference: ${difference >= 0 ? "+" : ""}${difference.toFixed(1)} percentage points`];
                } } }
            }
        }
    });
}

function signalLabel(comparison) {
    const item = largestDifference(comparison);
    const value = item ? Math.abs(item.difference) : 0;
    if (value >= 25) return "Large gap";
    if (value >= 10) return "Moderate gap";
    return "Small gap";
}

function updateObservation(data) {
    const successful = Number(data.total_generations) || 0;
    const genderValid = Number(data.valid_gender_analyses) || 0;
    const ageValid = Number(data.valid_age_analyses) || 0;
    const candidates = [];
    if (genderValid > 0 && hasAiValues(data.gender_comparison)) {
        candidates.push(...comparisonEntries(data.gender_comparison, "gender", genderValid));
    }
    if (ageValid > 0 && hasAiValues(data.age_group_comparison)) {
        candidates.push(...comparisonEntries(data.age_group_comparison, "age", ageValid));
    }
    candidates.sort((a, b) => Math.abs(b.difference) - Math.abs(a.difference));
    const strongest = candidates[0];
    const panel = document.getElementById("observation");
    if (!successful || !strongest) {
        panel.hidden = true;
        return;
    }
    const absoluteDifference = Math.abs(strongest.difference);
    const frequency = strongest.difference >= 0 ? "more" : "less";
    document.getElementById("observation-title").textContent = `${strongest.label} ${strongest.dimension} presentation`;
    document.getElementById("observation-text").textContent = absoluteDifference <= 0.05
        ? `In this sample, ${strongest.label} ${strongest.dimension} presentation matches the reference share.`
        : `In this sample, ${strongest.label} presentation appears ${absoluteDifference.toFixed(1)} percentage points ${frequency} frequently in generated images (${Number(strongest.ai_percentage).toFixed(1)}%) than in the reference dataset (${Number(strongest.real_world_percentage).toFixed(1)}%).`;
    document.getElementById("sample-warning").textContent = strongest.sampleSize < 10
        ? `Small sample warning: this observation is based on ${strongest.sampleSize} validated classification${strongest.sampleSize === 1 ? "" : "s"}.`
        : "";
    panel.hidden = false;
}

function comparisonEntries(comparison = {}, dimension, sampleSize) {
    return Object.entries(comparison).map(([label, values]) => ({ label, dimension, sampleSize, ...values }));
}

function renderGallery(images) {
    const gallery = document.getElementById("image-gallery");
    document.getElementById("gallery-count").textContent = `${images.length} image${images.length === 1 ? "" : "s"}`;
    gallery.replaceChildren();
    if (!images.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.innerHTML = "<strong>No generated evidence yet</strong><p>Successful analyzed images will appear here.</p>";
        gallery.appendChild(empty);
        return;
    }
    images.forEach((reference, index) => gallery.appendChild(createGalleryItem(reference, index)));
}

function createGalleryItem(reference, index) {
    const figure = document.createElement("figure");
    figure.className = "gallery-item";
    figure.tabIndex = 0;
    figure.setAttribute("role", "button");
    figure.setAttribute("aria-label", `Open successful sample ${index + 1}`);
    const image = document.createElement("img");
    image.loading = "lazy";
    image.alt = `Successful generated sample ${index + 1}`;
    image.src = cinemaImageSource(reference);
    image.addEventListener("error", () => {
        image.dataset.failed = "true";
        const fallback = document.createElement("div");
        fallback.className = "image-fallback";
        fallback.textContent = "Image unavailable";
        image.replaceWith(fallback);
        figure.removeAttribute("role");
        figure.removeAttribute("tabindex");
    }, { once: true });
    const caption = document.createElement("figcaption");
    caption.innerHTML = `<span>Sample ${String(index + 1).padStart(2, "0")}</span><strong>VALIDATED</strong>`;
    figure.append(image, caption);
    const open = () => { if (image.dataset.failed !== "true") openLightbox(image.src, `Successful sample ${index + 1}`); };
    figure.addEventListener("click", open);
    figure.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); open(); } });
    return figure;
}

async function loadPresentationBackupPanel(preferredId = null) {
    try {
        const [backups, active] = await Promise.all([fetchPresentationBackups(), fetchActivePresentationBackup()]);
        presentationBackups = backups || [];
        activePresentationBackup = active || null;
        selectedPresentationBackup = presentationBackups.find((item) => String(item.id) === String(preferredId))
            || presentationBackups.find((item) => item.is_active)
            || presentationBackups[0]
            || null;
        renderPresentationBackupPanel();
    } catch (error) {
        presentationBackups = [];
        activePresentationBackup = null;
        selectedPresentationBackup = null;
        renderPresentationBackupPanel(error.message || "Presentation Backup storage is unavailable");
    }
}

function renderPresentationBackupPanel(errorMessage = null) {
    const select = document.getElementById("backup-select");
    select.replaceChildren();
    if (!presentationBackups.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No backups";
        select.append(option);
    } else {
        presentationBackups.forEach((backup) => {
            const option = document.createElement("option");
            option.value = backup.id;
            option.textContent = `${backup.is_active ? "ACTIVE · " : ""}${backup.prompt_text} · ${backup.counts.validated}/${backup.counts.requested}`;
            option.selected = String(backup.id) === String(selectedPresentationBackup?.id);
            select.append(option);
        });
    }
    const backup = selectedPresentationBackup;
    document.getElementById("backup-panel-title").textContent = backup
        ? `${backup.is_active ? "Presentation Backup" : "Saved Backup"}: ${backup.prompt_text}`
        : "No presentation backup configured";
    document.getElementById("backup-panel-summary").textContent = errorMessage || (backup
        ? `${backup.counts.validated}/${backup.counts.requested} validated · Assets ${backup.verified_at ? "verified" : "awaiting integrity check"}${backup.is_active ? " · Active for recovery" : ""}`
        : "Save a completed experiment to create a persistent, provider-free replay.");
    const status = document.getElementById("backup-panel-status");
    status.textContent = errorMessage ? "NOT READY" : backup?.status?.replaceAll("_", " ") || "NOT READY";
    status.dataset.status = errorMessage ? "NOT_READY" : backup?.status || "NOT_READY";
    document.getElementById("btn-activate-backup").disabled = !backup || backup.is_active || backup.status === "BROKEN";
    document.getElementById("btn-verify-backup").disabled = !backup;
    document.getElementById("btn-open-backup-replay").disabled = !backup || backup.status === "BROKEN";
}

function selectPresentationBackup(event) {
    selectedPresentationBackup = presentationBackups.find((item) => String(item.id) === String(event.target.value)) || null;
    renderPresentationBackupPanel();
}

async function pinCurrentExperiment() {
    const experimentId = currentComparison?.experiment_id;
    const validated = Number(currentComparison?.validated_samples ?? currentComparison?.total_generations) || 0;
    if (!experimentId || validated < 1) return;
    const button = document.getElementById("btn-pin-experiment");
    button.disabled = true;
    try {
        const backup = await createPresentationBackup(experimentId, `${currentComparison.prompt_text} Presentation Backup`);
        await loadPresentationBackupPanel(backup.id);
        updatePreparedExperiment(currentComparison, currentExperimentResults, experimentId);
        setMeta("Presentation Backup saved with independent assets and a verified manifest. Activate it before the presentation.");
    } catch (error) {
        setMeta(error.message || "Presentation Backup could not be created.", true);
    } finally {
        button.disabled = false;
    }
}

function unpinExperiment() {
    setMeta("Persistent backups are never deleted from the dashboard. Activate another backup instead.");
}

async function openPreparedExperiment(backupOverride = null) {
    const backup = backupOverride || selectedPresentationBackup || activePresentationBackup;
    if (!backup || backup.status === "BROKEN") return;
    try {
        const payload = await fetchPresentationReplay(backup.id);
        startPreparedReplay(payload);
        markPresentationReplay(backup.id).catch(() => {});
    } catch (error) {
        setMeta(error.message || "Prepared Replay failed its integrity check.", true);
    }
}

function replayVerifiedExperiment() {
    const matching = presentationBackups.find((item) => String(item.source_experiment_id) === String(currentComparison?.experiment_id));
    if (matching) {
        selectedPresentationBackup = matching;
        openPreparedExperiment();
        return;
    }
    if (!currentComparison || !currentExperimentResults.length) return;
    const validated = Number(currentComparison.validated_samples ?? currentComparison.total_generations) || 0;
    if (validated < 1) return;
    const events = currentExperimentResults.map((result, index) => {
        const generated = result.generation_status === "success";
        const validatedResult = generated && result.analysis_status === "success";
        return {
            sample_index: index + 1,
            completed_order: index + 1,
            status: validatedResult ? "success" : generated ? "unverified" : "failed",
            phase: validatedResult ? "complete" : generated ? "analysis" : "generation",
            reason: result.display_message || (validatedResult ? "Saved validation result." : "Saved sample was excluded."),
            image_reference: result.image_reference,
            detected_person_count: result.detected_person_count || 0,
            detected_gender: result.detected_gender,
            detected_age_group: result.detected_age_group,
        };
    });
    const succeeded = events.filter((event) => event.status === "success").length;
    const unverified = events.filter((event) => event.status === "unverified").length;
    const failed = events.filter((event) => event.status === "failed").length;
    currentReplayPayload = {
        backup_id: null,
        source_experiment_id: currentComparison.experiment_id,
        prompt: { id: currentComparison.prompt_id, text: currentComparison.prompt_text },
        analysis: { provider: currentComparison.analysis_provider, model: currentComparison.analysis_model },
        counts: { requested: events.length }, results: events,
    };
    presentationContext = createPresentationContext({
        mode: "prepared_replay",
        experimentId: currentComparison.experiment_id,
        sourceExperimentId: currentComparison.experiment_id,
        promptId: currentComparison.prompt_id,
        promptText: currentComparison.prompt_text,
        analysisRevisionId: currentComparison.analysis_revision,
        analyzerProvider: currentComparison.analysis_provider,
        preparedSnapshot: currentReplayPayload,
    });
    openCinema(currentComparison.prompt_text, events.length, "replay");
    setCinemaStage("waiting", {
        kicker: "REPLAYING VERIFIED EXPERIMENT",
        title: "Saved evidence is returning to the cinema",
        message: "No new API requests. No images or analysis records will be created.",
    });
    cinemaEventQueue = events.map((event) => ({ ...event, total: events.length }));
    cinemaFinishRequested = true;
    playNextCinemaEvent();
}

function startPreparedReplay(payload) {
    currentReplayPayload = payload;
    presentationContext = createPresentationContext({
        mode: "prepared_replay",
        experimentId: payload.source_experiment_id || null,
        sourceExperimentId: payload.source_experiment_id || null,
        promptId: payload.prompt?.id || null,
        promptText: payload.prompt?.text || null,
        analysisRevisionId: payload.analysis?.revision_id ?? null,
        analyzerProvider: payload.analysis?.provider || null,
        preparedSnapshot: payload,
    });
    openCinema(payload.prompt.text, payload.counts.requested, "replay");
    setCinemaStage("waiting", {
        kicker: "PREPARED REPLAY — RECORDED RUN",
        title: "Recorded evidence is entering the cinema",
        message: "Replaying a previously completed and validated experiment. No generation or analysis API calls are being made.",
    });
    cinemaEventQueue = payload.results.map((event) => ({ ...event, total: payload.counts.requested }));
    cinemaFinishRequested = true;
    playNextCinemaEvent();
}

async function activateSelectedBackup() {
    if (!selectedPresentationBackup) return;
    try {
        await activatePresentationBackup(selectedPresentationBackup.id);
        await loadPresentationBackupPanel(selectedPresentationBackup.id);
        setMeta("Presentation Backup activated. It is now available in the live-failure recovery panel.");
    } catch (error) { setMeta(error.message || "Backup activation failed.", true); }
}

async function verifySelectedBackup() {
    if (!selectedPresentationBackup) return;
    try {
        const result = await verifyPresentationBackup(selectedPresentationBackup.id);
        await loadPresentationBackupPanel(selectedPresentationBackup.id);
        renderPreflightChecks(result.status, result.checks);
    } catch (error) { setMeta(error.message || "Integrity check failed.", true); }
}

async function runBackupPreflight() {
    try {
        const result = await runPresentationPreflight();
        renderPreflightChecks(result.status, result.checks);
        await loadPresentationBackupPanel(result.backup?.id);
    } catch (error) { renderPreflightChecks("NOT_READY", [{ name: "backend", status: "FAIL", detail: error.message }]); }
}

function renderPreflightChecks(status, checks = []) {
    const container = document.getElementById("preflight-results");
    container.hidden = false;
    container.replaceChildren();
    const heading = document.createElement("strong");
    heading.textContent = status.replaceAll("_", " ");
    container.append(heading);
    checks.forEach((check) => {
        const row = document.createElement("div");
        row.className = check.status === "PASS" ? "pass" : "fail";
        const badge = document.createElement("b"); badge.textContent = check.status;
        const text = document.createElement("span"); text.textContent = `${check.name.replaceAll("_", " ")} · ${check.detail}`;
        row.append(badge, text); container.append(row);
    });
}

function toggleReplayPause() {
    if (cinemaMode !== "replay") return;
    cinemaReplayPaused = !cinemaReplayPaused;
    document.getElementById("replay-pause").textContent = cinemaReplayPaused ? "Play" : "Pause";
    if (!cinemaReplayPaused) playNextCinemaEvent();
}

function restartPreparedReplay() {
    if (currentReplayPayload) startPreparedReplay(currentReplayPayload);
}

function skipReplaySample() {
    if (cinemaMode !== "replay") return;
    if (cinemaPlaybackTimer) window.clearTimeout(cinemaPlaybackTimer);
    cinemaPlaying = false;
    playNextCinemaEvent();
}

function openMethodology() {
    lastFocusedElement = document.activeElement;
    const modal = document.getElementById("methodology-modal");
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    modal.querySelector("button").focus();
}

function closeMethodology() {
    document.getElementById("methodology-modal").hidden = true;
    restoreModalFocus();
}

function openLightbox(src, caption) {
    lastFocusedElement = document.activeElement;
    document.getElementById("lightbox-image").src = src;
    document.getElementById("lightbox-caption").textContent = caption;
    const modal = document.getElementById("lightbox");
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    modal.querySelector("button").focus();
}

function closeLightbox() {
    const lightbox = document.getElementById("lightbox");
    lightbox.hidden = true;
    document.getElementById("lightbox-image").removeAttribute("src");
    restoreModalFocus();
}

function restoreModalFocus() {
    document.body.style.overflow = "";
    if (lastFocusedElement?.focus) lastFocusedElement.focus();
}

async function togglePresentation() {
    const entering = !document.body.classList.contains("presentation");
    document.body.classList.toggle("presentation", entering);
    if (entering && document.documentElement.requestFullscreen) {
        try { await document.documentElement.requestFullscreen(); } catch (_) { /* Layout mode remains available. */ }
    } else if (!entering && document.fullscreenElement) {
        try { await document.exitFullscreen(); } catch (_) { /* Browser can still leave layout mode. */ }
    }
    syncPresentationState();
}

function syncPresentationState() {
    const active = document.body.classList.contains("presentation");
    document.getElementById("btn-present").innerHTML = active ? "Exit presentation <kbd>P</kbd>" : "Presentation <kbd>P</kbd>";
    window.setTimeout(() => Object.values(charts).forEach((chart) => chart?.resize()), 180);
}

function handleFullscreenChange() {
    if (!document.fullscreenElement) document.body.classList.remove("presentation");
    syncPresentationState();
}

function handleKeyboard(event) {
    if (event.key === "Escape") {
        if (!document.getElementById("lightbox").hidden) closeLightbox();
        else if (!document.getElementById("methodology-modal").hidden) closeMethodology();
        else if (document.body.classList.contains("presentation")) {
            document.body.classList.remove("presentation");
            syncPresentationState();
        }
        return;
    }
    const tag = document.activeElement?.tagName;
    if (event.key.toLowerCase() === "p" && !["INPUT", "TEXTAREA", "SELECT"].includes(tag)) togglePresentation();
}

const delay = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function experimentForPrompt(promptId) {
    return sessionExperimentIds.get(promptId) || null;
}
