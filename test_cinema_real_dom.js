const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("frontend/index.html", "utf8");
const css = fs.readFileSync("frontend/styles/style_v3.css", "utf8");
const app = fs.readFileSync("frontend/js/app_v3.js", "utf8");

if ((html.match(/id="cinema-image"/g) || []).length !== 1) throw new Error("Expected one main Cinema image");
if (html.includes("cinema-image-backdrop") || css.includes("cinema-image-backdrop") || app.includes("cinema-image-backdrop")) throw new Error("Duplicate Cinema image layer remains");
if (!html.includes('id="cinema-image" class="cinema-image"')) throw new Error("Real main image is missing the selector used by Cinema CSS");

const finalForeground = [...css.matchAll(/\.cinema-active-frame \.cinema-image\{([^}]*)\}/g)].at(-1)?.[1] || "";
for (const token of ["object-fit:contain!important", "object-position:center center!important", "transform:none!important", "filter:none!important", "opacity:1!important", "position:relative!important"]) {
    if (!finalForeground.includes(token)) throw new Error(`Real foreground rule is missing ${token}`);
}
const finalStage = [...css.matchAll(/\.cinema-active-frame \.cinema-visual\{([^}]*)\}/g)].at(-1)?.[1] || "";
for (const token of ["display:flex", "align-items:center", "justify-content:center", "overflow:hidden"]) {
    if (!finalStage.includes(token)) throw new Error(`Real Cinema stage is missing ${token}`);
}
if (!css.includes(".timeline-item img") || !css.includes("object-fit:cover")) throw new Error("Filmstrip cover rule is missing");

const stageStart = app.indexOf("function setCinemaStage(state, content)");
const stageEnd = app.indexOf("function normalizeCinemaSource", stageStart);
const stage = app.slice(stageStart, stageEnd);
if (stage.includes("backgroundImage") || stage.includes("backdrop")) throw new Error("Stage renderer still creates a background image copy");
if (!stage.includes("image.src = content.imageSource")) throw new Error("Main image does not use the canonical full image source");
if (!app.includes("item.dataset.resultId") || !app.includes("image.dataset.resultId")) throw new Error("Result identity is not projected to both views");

console.log("CINEMA REAL DOM CONTRACT: PASS");
