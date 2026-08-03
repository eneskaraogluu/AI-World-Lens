const fs = require("fs");
const vm = require("vm");

const elements = new Map();
function element(id) {
    if (!elements.has(id)) {
        elements.set(id, {
            id,
            textContent: "",
            hidden: false,
            classList: {
                values: new Set(),
                toggle(name, force) {
                    if (force) this.values.add(name);
                    else this.values.delete(name);
                },
            },
        });
    }
    return elements.get(id);
}

const sandbox = {
    console,
    Map,
    Set,
    Chart: {
        defaults: { plugins: { tooltip: {} }, font: {} },
    },
    document: {
        addEventListener() {},
        getElementById: element,
    },
    window: { setTimeout, clearTimeout, setInterval, clearInterval },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("frontend/js/app_v3.js", "utf8"), sandbox);

const failedOnly = {
    total_generations: 0,
    failed_generations: 10,
    valid_person_analyses: 0,
    valid_gender_analyses: 0,
    valid_age_analyses: 0,
    source: "Reference",
    gender_comparison: {
        Male: { real_world_percentage: 78, ai_percentage: 0, difference: -78 },
        Female: { real_world_percentage: 22, ai_percentage: 0, difference: -22 },
    },
    age_group_comparison: {},
};

sandbox.updateStats(failedOnly);
if (element("stat-gap").textContent !== "—") throw new Error("Failed-only data produced a deviation");
if (element("gender-deviation-card").classList.values.has("deviation-alert")) throw new Error("Failed-only data produced an alert");

const fresh = sandbox.freshSessionComparison(failedOnly);
if (fresh.failed_generations !== 0 || fresh.gender_comparison.Male.difference !== 0) throw new Error("Historical data leaked into a fresh session");

const measured = JSON.parse(JSON.stringify(failedOnly));
measured.total_generations = 1;
measured.failed_generations = 0;
measured.valid_person_analyses = 1;
measured.valid_gender_analyses = 1;
measured.valid_age_analyses = 1;
measured.gender_comparison.Male.ai_percentage = 100;
measured.gender_comparison.Male.difference = 22;
measured.gender_comparison.Female.ai_percentage = 0;
measured.gender_comparison.Female.difference = -22;
sandbox.updateStats(measured);
if (element("stat-gap").textContent !== "22.0%") throw new Error("Measured deviation was not displayed");
if (!element("gender-deviation-card").classList.values.has("deviation-alert")) throw new Error("Measured deviation did not produce an alert");

console.log("FRONTEND INTEGRITY: PASS");
