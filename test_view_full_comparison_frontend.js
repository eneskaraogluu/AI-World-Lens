const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("frontend/js/app_v3.js", "utf8");

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...names) { names.forEach((name) => this.values.add(name)); }
    remove(...names) { names.forEach((name) => this.values.delete(name)); }
    toggle(name, force) {
        const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
        if (enabled) this.values.add(name); else this.values.delete(name);
        return enabled;
    }
}

class FakeElement {
    constructor(id = "") {
        this.id = id;
        this.dataset = {};
        this.textContent = "";
        this.disabled = false;
        this.hidden = false;
        this.classList = new FakeClassList();
        this.attributes = {};
        this.scrolled = false;
        this.focused = false;
    }
    addEventListener() {}
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    querySelector() { return new FakeElement(); }
    scrollIntoView() { this.scrolled = true; }
    focus() { this.focused = true; }
}

const elements = new Map();
const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
};
const promptButtons = [new FakeElement("engineer"), new FakeElement("doctor")];
promptButtons[0].dataset.id = "prompt-engineer";
promptButtons[1].dataset.id = "prompt-doctor";

const sandbox = {
    console,
    Map,
    Set,
    Chart: { defaults: { plugins: { tooltip: {} }, font: {} } },
    document: {
        addEventListener() {},
        getElementById: element,
        querySelectorAll(selector) { return selector === ".prompt-btn" ? promptButtons : []; },
        querySelector() { return new FakeElement(); },
    },
    window: {
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
        requestAnimationFrame(callback) { callback(); },
    },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

async function successfulPreparedReplayTransition() {
    element("loadingOverlay").classList.add("active");
    element("cinema-view-comparison").textContent = "View Full Comparison";
    vm.runInContext(`
        updateRunButton = () => {};
        presentationContext = createPresentationContext({
            mode: "prepared_replay",
            sourceExperimentId: "42",
            promptId: "prompt-doctor",
            promptText: "A doctor",
            analysisRevisionId: 1,
            analyzerProvider: "gemini",
            preparedSnapshot: { results: [{ sample_index: 1 }] },
        });
        __loadCalls = [];
        __chartResizes = 0;
        __chartUpdates = 0;
        charts = { gender: { resize(){ __chartResizes += 1; }, update(){ __chartUpdates += 1; } }, age: null };
        __resolveLoad = null;
        loadDashboardData = (request) => {
            __loadCalls.push(request);
            return new Promise((resolve) => {
                __resolveLoad = () => {
                    currentComparison = {
                        experiment_id: "42", prompt_id: "prompt-doctor", prompt_text: "A doctor",
                        analysis_revision: 1, analysis_provider: "gemini"
                    };
                    resolve(true);
                };
            });
        };
    `, sandbox);

    const first = vm.runInContext("handleViewFullComparison()", sandbox);
    const second = vm.runInContext("handleViewFullComparison()", sandbox);
    if (!element("cinema-view-comparison").disabled) throw new Error("Comparison button was not disabled while loading");
    if (!element("loadingOverlay").classList.values.has("active")) throw new Error("Cinema closed before dashboard loading completed");
    if (vm.runInContext("__loadCalls.length", sandbox) !== 1) throw new Error("Double click started duplicate dashboard loads");
    vm.runInContext("__resolveLoad()", sandbox);
    await Promise.all([first, second]);

    const request = vm.runInContext("__loadCalls[0]", sandbox);
    if (request.experimentId !== "42" || request.promptId !== "prompt-doctor") throw new Error("Prepared Replay did not target source experiment 42 and its prompt");
    if (element("loadingOverlay").classList.values.has("active")) throw new Error("Cinema remained open after successful dashboard load");
    if (!promptButtons[1].classList.values.has("active") || promptButtons[0].classList.values.has("active")) throw new Error("Replay prompt did not replace the stale selected prompt");
    if (!element("comparison-heading").scrolled || !element("comparison-heading").focused) throw new Error("Comparison section was not scrolled to and focused");
    if (vm.runInContext("__chartResizes", sandbox) !== 1 || vm.runInContext("__chartUpdates", sandbox) !== 1) throw new Error("Visible charts were not resized and updated");
}

async function failedTransitionStaysInCinema() {
    element("loadingOverlay").classList.add("active");
    vm.runInContext(`
        presentationContext = createPresentationContext({
            mode: "prepared_replay", sourceExperimentId: "42",
            promptId: "prompt-doctor", promptText: "A doctor",
            preparedSnapshot: { results: [] }
        });
        loadDashboardData = async () => false;
    `, sandbox);
    await vm.runInContext("handleViewFullComparison()", sandbox);
    if (!element("loadingOverlay").classList.values.has("active")) throw new Error("Cinema closed after a comparison load failure");
    if (element("cinema-view-comparison").disabled) throw new Error("Retry remained disabled after a comparison load failure");
    if (!element("cinema-completion-summary").textContent.includes("legacy replay")) throw new Error("Safe legacy replay message was not shown");
}

async function verifiedOfflineSnapshotTransition() {
    element("loadingOverlay").classList.add("active");
    vm.runInContext(`
        presentationContext = createPresentationContext({
            mode: "prepared_replay", sourceExperimentId: "42",
            promptId: "prompt-doctor", promptText: "A doctor",
            preparedSnapshot: { dashboard: {
                verified: true, experiment_id: "42", prompt_id: "prompt-doctor",
                comparison: { experiment_id: "42", prompt_id: "prompt-doctor", prompt_text: "A doctor", analysis_revision: 1, analysis_provider: "gemini" },
                results: []
            } }
        });
        loadDashboardData = async () => false;
        applyDashboardData = (comparison) => { currentComparison = comparison; currentExperimentResults = []; };
    `, sandbox);
    await vm.runInContext("handleViewFullComparison()", sandbox);
    if (element("loadingOverlay").classList.values.has("active")) throw new Error("Verified offline dashboard snapshot did not open the comparison");
    if (!element("current-prompt-meta").textContent.includes("Prepared verified experiment #42")) throw new Error("Offline snapshot was presented as live data");
}

function sourceContractChecks() {
    const handlerStart = source.indexOf("async function handleViewFullComparison()");
    const handlerEnd = source.indexOf("function updateCinema", handlerStart);
    const handler = source.slice(handlerStart, handlerEnd);
    for (const forbidden of ["runExperiment(", "reanalyzeExperiment(", "fetchExperimentStatus("]) {
        if (handler.includes(forbidden)) throw new Error(`Comparison transition starts live work: ${forbidden}`);
    }
    for (const required of ["fetchExperimentComparison(experimentId)", "fetchExperimentResults(experimentId)", "updateStats(data)", "updateCharts(data)", "renderGallery("]) {
        if (!source.includes(required)) throw new Error(`Dashboard load contract is missing ${required}`);
    }
    const liveTarget = vm.runInContext("presentationTargetExperimentId(createPresentationContext({ mode: 'live', experimentId: '57' }))", sandbox);
    if (liveTarget !== "57") throw new Error("Live Cinema does not resolve its completed experiment ID");
    const preparedTarget = vm.runInContext("presentationTargetExperimentId(createPresentationContext({ mode: 'prepared_replay', experimentId: '41', sourceExperimentId: '42' }))", sandbox);
    if (preparedTarget !== "42") throw new Error("Prepared Replay mixed another same-prompt experiment into the dashboard");
}

(async () => {
    sourceContractChecks();
    await successfulPreparedReplayTransition();
    await verifiedOfflineSnapshotTransition();
    await failedTransitionStaysInCinema();
    console.log("VIEW FULL COMPARISON FRONTEND: PASS");
})().catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
});
