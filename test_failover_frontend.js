const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("frontend/index.html", "utf8");
const apiSource = fs.readFileSync("frontend/js/api.js", "utf8");
const appSource = fs.readFileSync("frontend/js/app_v3.js", "utf8");

const referencedIds = [...appSource.matchAll(/getElementById\("([^"]+)"\)/g)].map((match) => match[1]);
for (const id of new Set(referencedIds)) {
    if (!html.includes(`id="${id}"`)) throw new Error(`Missing DOM element: ${id}`);
}

const sandbox = {
    console,
    Map,
    Set,
    fetch: async () => ({
        ok: false,
        status: 404,
        async json() { return { detail: "Experiment not found" }; },
    }),
    Chart: { defaults: { plugins: { tooltip: {} }, font: {} } },
    document: {
        addEventListener() {},
        getElementById() { return { classList: { toggle() {}, add() {}, remove() {} } }; },
        querySelectorAll() { return []; },
    },
    window: {
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
    },
};

vm.createContext(sandbox);
vm.runInContext(apiSource, sandbox);
vm.runInContext(appSource, sandbox);

(async () => {
    if (appSource.includes("storageSetPinned") || appSource.includes("PINNED_STORAGE_KEY")) {
        throw new Error("Presentation safety still depends on a browser-local pin");
    }

    const replayStart = appSource.indexOf("function replayVerifiedExperiment()");
    const replayEnd = appSource.indexOf("function openMethodology()", replayStart);
    const replayBody = appSource.slice(replayStart, replayEnd);
    for (const forbidden of ["runExperiment(", "reanalyzeExperiment(", "enqueue_task"]) {
        if (replayBody.includes(forbidden)) throw new Error(`Replay contains a live call: ${forbidden}`);
    }
    if (!appSource.includes("fetchPresentationReplay") || !replayBody.includes("currentExperimentResults")) throw new Error("Replay sources are incomplete");
    if (!replayBody.includes("No new API requests")) throw new Error("Replay disclosure is missing");

    const pinStart = appSource.indexOf("function pinCurrentExperiment()");
    const pinEnd = appSource.indexOf("function unpinExperiment()", pinStart);
    const pinBody = appSource.slice(pinStart, pinEnd);
    if (!pinBody.includes("validated < 1")) throw new Error("Pinning does not require a validated result");

    console.log("FAILOVER FRONTEND: PASS");
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
