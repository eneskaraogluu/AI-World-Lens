const fs = require("fs");

const html = fs.readFileSync("frontend/index.html", "utf8");
const api = fs.readFileSync("frontend/js/api.js", "utf8");
const app = fs.readFileSync("frontend/js/app_v3.js", "utf8");

for (const text of [
    "Save as Presentation Backup",
    "Run Presentation Preflight",
    "PREPARED REPLAY — RECORDED RUN",
    "Recorded run · No generation or analysis API calls",
]) {
    if (!html.includes(text)) throw new Error(`Missing presentation safety disclosure: ${text}`);
}

for (const endpoint of [
    "/presentation/backups/from-experiment/",
    "/presentation/backups/active",
    "/presentation/preflight",
    "/replay",
]) {
    if (!api.includes(endpoint)) throw new Error(`Missing Presentation Backup API binding: ${endpoint}`);
}

if (app.includes("PINNED_STORAGE_KEY") || app.includes("storageGetPinned")) {
    throw new Error("Persistent backup still depends on the legacy localStorage pin");
}
for (const canonicalMode of ['presentationMode === "prepared_replay"', 'presentationMode === "legacy_replay"']) {
    if (!app.includes(canonicalMode)) throw new Error(`Missing canonical presentation state: ${canonicalMode}`);
}
if (!app.includes('"LEGACY RECORDED RUN"') || !app.includes('"PREPARED REPLAY — RECORDED RUN"')) {
    throw new Error("Replay badges are not separated from LIVE mode");
}
if (!app.includes('cinemaMode !== "live"') || !app.includes("activePresentationBackup")) {
    throw new Error("Live failure recovery is not gated by an active backup");
}

const replayStart = app.indexOf("function startPreparedReplay(payload)");
const replayEnd = app.indexOf("async function activateSelectedBackup", replayStart);
const replayBody = app.slice(replayStart, replayEnd);
for (const forbidden of ["runExperiment(", "reanalyzeExperiment(", "fetchExperimentStatus(", "enqueue_task"]){
    if (replayBody.includes(forbidden)) throw new Error(`Prepared Replay contains live work: ${forbidden}`);
}
if (!replayBody.includes("playNextCinemaEvent")) throw new Error("Prepared Replay does not reuse the Cinema playback engine");
if (!app.includes('split("/").map(encodeURIComponent).join("/")')) throw new Error("Nested backup asset paths are not encoded safely");

console.log("PRESENTATION BACKUP FRONTEND: PASS");
