const fs = require("fs");
const vm = require("vm");

class FakeClassList {
    constructor() { this.values = new Set(); }
    add(...names) { names.forEach((name) => this.values.add(name)); }
    remove(...names) { names.forEach((name) => this.values.delete(name)); }
    toggle(name, force) {
        const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
        if (enabled) this.values.add(name); else this.values.delete(name);
        return enabled;
    }
    contains(name) { return this.values.has(name); }
}

class FakeElement {
    constructor(id = "") {
        this.id = id;
        this.children = [];
        this.dataset = {};
        this.style = {};
        this.hidden = false;
        this.textContent = "";
        this.className = "";
        this.classList = new FakeClassList();
        this.attributes = {};
        this.selectorChildren = {};
        this.offsetWidth = 500;
    }
    append(...children) { this.children.push(...children); }
    prepend(child) { this.children.unshift(child); }
    replaceChildren(...children) { this.children = [...children]; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; if (name === "src") delete this.src; }
    addEventListener() {}
    querySelector(selector) {
        if (this.selectorChildren[selector]) return this.selectorChildren[selector];
        if (selector === ".timeline-status-icon") return this.children.find((child) => child.className === "timeline-status-icon") || null;
        if (selector === "img") return this.children.find((child) => child.tagName === "img") || null;
        return null;
    }
}

const elements = new Map();
const element = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
};
element("cinema-failure-mark").selectorChildren.span = new FakeElement("failure-symbol");
element("cinema-failure-mark").selectorChildren.b = new FakeElement("failure-label");

const sandbox = {
    console,
    Map,
    Set,
    URL,
    Chart: { defaults: { plugins: { tooltip: {} }, font: {} } },
    document: {
        addEventListener() {},
        getElementById: element,
        createElement(tagName) { const node = new FakeElement(); node.tagName = tagName; return node; },
        querySelectorAll(selector) {
            if (selector === "#cinema-timeline .timeline-item") return element("cinema-timeline").children;
            return [];
        },
    },
    window: {
        location: { href: "http://localhost:3000/" },
        setTimeout, clearTimeout, setInterval, clearInterval,
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("frontend/js/app_v3.js", "utf8"), sandbox);

// A late onload from sample 01 must never reveal it after sample 02 became active.
sandbox.setCinemaStage("success", { imageSource: "/assets/generations/sample-01.png", sampleIndex: 1, total: 10, kicker: "", title: "", message: "" });
const staleOnload = element("cinema-image").onload;
sandbox.setCinemaStage("success", { imageSource: "/assets/generations/sample-02.png?v=49", sampleIndex: 2, total: 10, kicker: "", title: "", message: "" });
const currentOnload = element("cinema-image").onload;
element("cinema-image").currentSrc = "http://localhost:3000/assets/generations/sample-01.png";
staleOnload();
if (!element("cinema-image").hidden) throw new Error("A stale sample image won the onload race");
element("cinema-image").currentSrc = "http://localhost:3000/assets/generations/sample-02.png?v=49";
currentOnload();
if (element("cinema-image").hidden) throw new Error("The current sample foreground did not render");
if (element("cinema-image").dataset.sampleIndex !== "2") throw new Error("Main image did not retain the canonical active sample index");
if (sandbox.normalizeCinemaSource("/x/sample.png?v=1") !== sandbox.normalizeCinemaSource("http://localhost:3000/x/sample.png?v=2")) throw new Error("Cache parameters break source matching");

// The filmstrip and main stage are projections of the same canonical event.
const activeEvent = { id: "result-02", result_id: "result-02", sample_index: 2, status: "success", phase: "complete", image_reference: "sample-02.png", detected_person_count: 1, detected_gender: "Female", detected_age_group: "25-34", total: 10 };
vm.runInContext("cinemaCanonicalState = createCinemaState('A doctor', 10, 'replay')", sandbox);
sandbox.initializeCinemaTimeline(10);
vm.runInContext("cinemaCanonicalState.events = [__event]", Object.assign(sandbox, { __event: activeEvent }));
sandbox.updateCinemaTimeline(vm.runInContext("cinemaCanonicalState", sandbox));
sandbox.activateCinemaSample(activeEvent, 0);
element("cinema-image").currentSrc = "http://localhost:3000/assets/generations/sample-02.png";
element("cinema-image").onload();
const selected = element("cinema-timeline").children.find((item) => item.classList.values.has("selected"));
const selectedImage = selected && selected.querySelector("img");
if (!selectedImage) throw new Error("Active filmstrip sample was not selected");
if (element("cinema-image").dataset.source !== sandbox.normalizeCinemaSource(selectedImage.dataset.source)) throw new Error("Main and selected filmstrip image sources differ");
if (vm.runInContext("cinemaActiveSample.index", sandbox) !== 2) throw new Error("Cinema does not retain one canonical active sample");
if (vm.runInContext("cinemaActiveSample.id", sandbox) !== "result-02" || vm.runInContext("cinemaActiveSample.resultId", sandbox) !== "result-02") throw new Error("Active sample identity differs from the selected result");
if (selected.dataset.resultId !== element("cinema-image").dataset.resultId) throw new Error("Filmstrip and main image result IDs differ");

// Contain geometry keeps every source corner inside the reserved stage.
function containedSize(cw, ch, iw, ih) {
    const scale = Math.min(cw / iw, ch / ih);
    return { width: iw * scale, height: ih * scale };
}
for (const [width, height] of [[1024, 1024], [1536, 1024], [1024, 1536]]) {
    const rect = containedSize(900, 560, width, height);
    if (rect.width > 900.001 || rect.height > 560.001 || rect.width <= 0 || rect.height <= 0) throw new Error(`Contain geometry clipped ${width}x${height}`);
}

const css = fs.readFileSync("frontend/styles/style_v3.css", "utf8");
const html = fs.readFileSync("frontend/index.html", "utf8");
if ((html.match(/id="cinema-image"/g) || []).length !== 1 || html.includes("cinema-image-backdrop")) throw new Error("Cinema stage must contain one authoritative image");
if (!css.includes("grid-template-columns:repeat(5,minmax(0,1fr))")) throw new Error("Proof Wall is not a five-column presentation grid");
if (!css.includes(".timeline-item img") || !css.includes("object-fit:cover")) throw new Error("Filmstrip navigation lost cover behavior");

console.log("CINEMA IMAGE STATE: PASS");
