const fs = require("fs");

const css = fs.readFileSync("frontend/styles/style_v3.css", "utf8");
const html = fs.readFileSync("frontend/index.html", "utf8");
const app = fs.readFileSync("frontend/js/app_v3.js", "utf8");

const blocks = (selector) => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return [...css.matchAll(new RegExp(`(?:^|})\\s*${escaped}\\{([^}]*)\\}`, "g"))].map((match) => match[1]);
};

const cinemaBlocks = blocks(".cinema-image");
if (!cinemaBlocks.length) throw new Error("Missing existing .cinema-image CSS rule");
for (const declaration of cinemaBlocks) {
    if (!declaration.includes("object-fit:contain")) throw new Error("Cinema main image is not contain");
    if (declaration.includes("object-fit:cover")) throw new Error("Cinema main image still uses cover");
    if (declaration.includes("transform:scale")) throw new Error("Cinema main image still uses scale");
    if (/min-width:(?!0)/.test(declaration)) throw new Error("Cinema main image forces min-width");
}
if (!cinemaBlocks.some((declaration) => declaration.includes("object-position:center"))) {
    throw new Error("Cinema main image is not centered");
}

const lightboxBlocks = blocks(".lightbox-panel img");
if (lightboxBlocks.length !== 1) throw new Error("Expected the existing lightbox image rule");
for (const token of ["object-fit:contain", "object-position:center", "transform:none"]) {
    if (!lightboxBlocks[0].includes(token)) throw new Error(`Lightbox image is missing ${token}`);
}

if (!blocks(".timeline-item img").some((declaration) => declaration.includes("object-fit:cover"))) {
    throw new Error("Filmstrip thumbnail cover behavior changed");
}
const galleryBlocks = blocks(".gallery-item img");
const effectiveGalleryRule = galleryBlocks[galleryBlocks.length - 1] || "";
if (!effectiveGalleryRule.includes("object-fit:contain")) {
    throw new Error("Proof Wall evidence is not contain");
}
if (effectiveGalleryRule.includes("object-fit:cover")) {
    throw new Error("Effective Proof Wall evidence rule still uses cover");
}

if (html.includes("cinema-image-backdrop") || css.includes(".cinema-image-backdrop") || app.includes('getElementById("cinema-image-backdrop")')) {
    throw new Error("Cinema still contains a duplicate blur/background image layer");
}
const foregroundBlocks = [...css.matchAll(/\.cinema-active-frame \.cinema-image\{([^}]*)\}/g)].map((match) => match[1]);
if (!foregroundBlocks.some((declaration) => declaration.includes("z-index:1") && declaration.includes("opacity:1"))) {
    throw new Error("Cinema foreground is not authoritative and fully opaque");
}

const stageStart = app.indexOf("function setCinemaStage(state, content)");
const stageEnd = app.indexOf("function initializeCinemaTimeline", stageStart);
const stageBody = app.slice(stageStart, stageEnd);
for (const forbidden of ["naturalWidth", "naturalHeight", "style.aspectRatio", "aspect-ratio"]) {
    if (stageBody.includes(forbidden)) throw new Error(`JavaScript still changes image geometry: ${forbidden}`);
}

if ((html.match(/id="cinema-image"/g) || []).length !== 1) throw new Error("Live and replay no longer share one Cinema image");
if (!app.slice(app.indexOf("function startPreparedReplay"), app.indexOf("async function activateSelectedBackup")).includes("openCinema")) {
    throw new Error("Prepared Replay no longer uses the existing Cinema image path");
}
if (!html.includes("style_v3.css?v=50") || !html.includes("app_v3.js?v=50")) {
    throw new Error("Frontend cache version was not advanced");
}

console.log("IMAGE FIT FRONTEND: PASS");
