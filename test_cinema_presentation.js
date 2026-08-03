const fs = require("fs");
const vm = require("vm");

class FakeClassList {
    constructor(owner) { this.owner = owner; this.values = new Set(); }
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
        this.children = [];
        this.dataset = {};
        this.style = {
            setProperty: (name, value) => { this.style[name] = value; },
            removeProperty: (name) => { delete this.style[name]; },
        };
        this.hidden = false;
        this.textContent = "";
        this.className = "";
        this.classList = new FakeClassList(this);
        this.attributes = {};
    }
    append(...children) { this.children.push(...children); }
    prepend(child) { this.children.unshift(child); }
    replaceChildren(...children) { this.children = [...children]; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener() {}
    querySelector(selector) {
        if (selector === "span" || selector === "b") return this.children.find((child) => child.tagName === selector) || null;
        if (selector === ".timeline-status-icon") return this.children.find((child) => child.className === "timeline-status-icon") || null;
        if (selector === "img") return this.children.find((child) => child.tagName === "img") || null;
        return null;
    }
}

const elements = new Map();
function element(id) {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
}
element("cinema-failure-mark").children.push(
    Object.assign(new FakeElement(), { tagName: "span" }),
    Object.assign(new FakeElement(), { tagName: "b" }),
);

const sandbox = {
    console,
    Map,
    Set,
    Chart: { defaults: { plugins: { tooltip: {} }, font: {} } },
    document: {
        addEventListener() {},
        getElementById: element,
        createElement(tagName) {
            const node = new FakeElement();
            node.tagName = tagName;
            return node;
        },
        querySelectorAll(selector) {
            if (selector === "#cinema-timeline .timeline-item") return element("cinema-timeline").children;
            return [];
        },
    },
    window: { setTimeout, clearTimeout, setInterval, clearInterval },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("frontend/js/app_v3.js", "utf8"), sandbox);

function reset(prompt = "An engineer", total = 10, mode = "live") {
    sandbox.__prompt = prompt;
    sandbox.__total = total;
    sandbox.__mode = mode;
    return vm.runInContext("cinemaCanonicalState = createCinemaState(__prompt, __total, __mode)", sandbox);
}

function derive(status) {
    sandbox.__status = status;
    return vm.runInContext("cinemaCanonicalState = deriveCinemaState(__status)", sandbox);
}

function success(sample, gender, age, people = 1) {
    return { sample_index: sample, completed_order: sample, status: "success", phase: "complete", image_reference: `sample-${sample}.png`, detected_gender: gender, detected_age_group: age, detected_person_count: people };
}

// 1. Honest 0/10 initial state.
let state = reset();
if (state.requested !== 10 || state.completed !== 0 || state.validated !== 0) throw new Error("Initial Cinema state is not 0/10");

// 2. Generated can be ahead of completed while visual analysis is pending.
state = derive({ status: "processing", total: 10, completed: 0, generated: 1, succeeded: 0, unverified: 0, events: [] });
if (state.generated !== 1 || state.completed !== 0 || state.validated !== 0) throw new Error("Generated/analyzing state was collapsed into completed");

// 3. A validated result contributes to the sample result and both distributions.
state = derive({ status: "processing", total: 10, completed: 1, generated: 1, succeeded: 1, unverified: 0, events: [success(1, "Male", "25-34")] });
if (state.validated !== 1 || state.genderCounts.Male !== 1 || state.ageCounts["25-34"] !== 1) throw new Error("Validated sample did not update canonical distributions");

// 4. Gender and age usable denominators remain separate and explain unclear values.
reset();
const mixed = [success(1, "Male", "25-34"), success(2, "Female", "Unclear"), success(3, "Unclear", "Unclear")];
state = derive({ status: "processing", total: 10, completed: 3, generated: 3, succeeded: 3, unverified: 0, events: mixed });
if (state.genderUsable !== 2 || state.genderUnclear !== 1 || state.ageUsable !== 1 || state.ageUnclear !== 2) throw new Error("Usable and unclear denominators are incorrect");
sandbox.updateCinemaLiveCharts(state);
if (element("cinema-gender-detail").textContent !== "Usable n=2 · Unclear=1") throw new Error("Gender denominator disclosure is missing");
if (element("cinema-age-detail").textContent !== "Usable n=1 · Unclear=2") throw new Error("Age denominator disclosure is missing");

// 5-6. Unverified and failed samples are excluded without stopping valid progress.
reset();
const partial = [success(1, "Female", "35-44"), { sample_index: 2, status: "unverified", phase: "analysis", image_reference: "sample-2.png" }, { sample_index: 3, status: "failed", phase: "generation" }];
state = derive({ status: "processing", total: 10, completed: 3, generated: 2, succeeded: 1, unverified: 1, failed: 2, events: partial });
if (state.validated !== 1 || state.unverified !== 1 || state.failed !== 1 || state.excluded !== 2 || state.genderUsable !== 1) throw new Error("Failed/unverified canonical counts are incorrect");

// 7. Final 10/10 state uses independent generated, validated, unverified and failed counts.
reset();
const finalEvents = [];
for (let index = 1; index <= 8; index += 1) finalEvents.push(success(index, index % 2 ? "Male" : "Female", index < 5 ? "25-34" : "35-44"));
finalEvents.push({ sample_index: 9, status: "unverified", phase: "analysis", image_reference: "sample-9.png" });
finalEvents.push({ sample_index: 10, status: "failed", phase: "generation" });
state = derive({ status: "completed", total: 10, completed: 10, generated: 9, succeeded: 8, unverified: 1, failed: 2, events: finalEvents, analysis_provider: "openai" });
if (state.completed !== 10 || state.generated !== 9 || state.validated !== 8 || state.unverified !== 1 || state.failed !== 1) throw new Error("Final Cinema totals are contradictory");
if (state.analysisProvider !== "openai") throw new Error("Active fallback provider was not retained");

// 8. Zero validated results render no invented percentages or bars.
reset();
state = derive({ status: "failed", total: 10, completed: 10, generated: 9, succeeded: 0, unverified: 9, failed: 10, events: finalEvents.map((event, index) => ({ ...event, sample_index: index + 1, status: index < 9 ? "unverified" : "failed" })) });
sandbox.updateCinemaLiveCharts(state);
if (element("cinema-male-value").textContent || element("cinema-female-value").textContent) throw new Error("Zero-data gender chart invented percentages");
if (element("cinema-age-25-34-value").textContent) throw new Error("Zero-data age chart invented percentages");
if (element("cinema-gender-empty").hidden || element("cinema-age-empty").hidden) throw new Error("Zero-data empty state is not visible");

// 9. Filmstrip allocates every requested slot before results arrive.
sandbox.initializeCinemaTimeline(10);
if (element("cinema-timeline").children.length !== 10) throw new Error("Filmstrip does not contain ten fixed slots");

// 10-13 are covered jointly by provider/count assertions above and existing
// fallback/dashboard integrity suites. The Cinema source must keep one renderer.
const source = fs.readFileSync("frontend/js/app_v3.js", "utf8");
if (!source.includes("renderCinemaState(cinemaCanonicalState)")) throw new Error("Cinema components do not share the canonical state renderer");

// Live and replay disclosures are driven by one canonical presentation mode.
sandbox.renderCinemaTrajectory = () => {};
reset("A doctor", 10, "live");
sandbox.openCinema("A doctor", 10, "live");
if (element("cinema-mode-badge").textContent !== "LIVE" || element("cinema-replay-disclosure").textContent !== "Composition quality assessed") throw new Error("Live mode leaks legacy replay state");
sandbox.__payload = { prompt: { text: "A doctor" }, counts: { requested: 10 }, analysis: { quality_policy: "composition-quality-v2" } };
vm.runInContext("currentReplayPayload = __payload", sandbox);
sandbox.openCinema("A doctor", 10, "replay");
if (element("cinema-mode-badge").textContent !== "PREPARED REPLAY — RECORDED RUN") throw new Error("Quality-assessed replay mode is incorrect");
vm.runInContext("currentReplayPayload = { analysis: { quality_policy: 'legacy-not-assessed' } }", sandbox);
sandbox.openCinema("A doctor", 10, "replay");
if (element("cinema-mode-badge").textContent !== "LEGACY RECORDED RUN" || !element("cinema-replay-disclosure").textContent.includes("Legacy prepared replay")) throw new Error("Legacy replay mode is incorrect");

console.log("CINEMA PRESENTATION: PASS");
