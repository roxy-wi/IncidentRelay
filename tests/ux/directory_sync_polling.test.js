"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
const timers = new Map();
const requests = [];
const errors = [];
const handlers = new Map();
let nextTimer = 0;
let refreshes = 0;
const context = {
    window: {}, document: {body: {contains: () => false}},
    location: {pathname: "/admin/directory-sync"},
    i18n: {t: key => key},
    setTimeout: callback => { timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    apiGet: (url, success, failure) => requests.push({url, success, failure}),
    showApiError: error => errors.push(error),
    openAppModal() {}, closeAppModal() {}, setAppModalSaving() {},
    $: selector => {
        if (!elements.has(selector)) {
            const element = {value: "", properties: {}, attributes: {}};
            for (const name of ["on", "empty", "append", "scrollTop", "trigger", "toggleClass", "addClass", "find", "closest", "each"]) {
                element[name] = () => element;
            }
            element.on = (_event, target, callback) => { handlers.set(target, callback); return element; };
            element.prop = (key, value) => {
                if (value === undefined) return element.properties[key];
                element.properties[key] = value;
                return element;
            };
            element.attr = (key, value) => {
                if (value === undefined) return element.attributes[key];
                element.attributes[key] = value;
                return element;
            };
            element.val = value => { element.value = value; return element; };
            element.is = () => false;
            element.text = value => { element.value = value; return element; };
            elements.set(selector, element);
        }
        return elements.get(selector);
    },
};
context.AppLoading = {
    clear: selector => context.$(selector).text(""),
    showBlock: (selector, message) => context.$(selector).text(message),
    setButtonLoading: (selector, busy) => context.$(selector).prop("loading", busy),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("app/static/js/pages/cmdb_sync.js", "utf8"), context);
vm.runInContext(fs.readFileSync("app/static/js/pages/directory_sync.js", "utf8"), context);
vm.runInContext("directorySyncOptions = {preset: {}, groups: [], teams: []}", context);
context.loadDirectorySync = () => { refreshes++; };

function tick() {
    assert.equal(timers.size, 1, "only one status timer may be pending");
    const [id, callback] = timers.entries().next().value;
    timers.delete(id);
    callback();
}

const source = {id: 1, name: "Source", config: {}, approved: true};
context.editDirectorySync(source.id);
assert.equal(requests.length, 1, "Configure only reads the source");
assert.equal(requests[0].url, "/api/admin/directory-sync/1");
requests.shift().success(source);
assert.equal(timers.size, 0, "opening an idle source does not poll");
context.openDirectorySync({...source, pending_mode: "run"});
tick();
assert.equal(requests[0].url, "/api/admin/directory-sync/1");
requests.shift().success({...source, running: true});
assert.equal(timers.size, 1, "keep monitoring the active operation");
tick();
requests.shift().success({...source, current_error: "current: unknown status"});
assert.equal(timers.size, 0, "current-duty errors alone must not keep polling");
assert.equal(elements.get("#ds-status").value, "current: unknown status", "completion must preserve the error");
assert.equal(refreshes, 1);

context.openDirectorySync({...source, running: true});
tick();
requests.shift().success(source);
assert.equal(elements.get("#ds-status").value, "ds.complete");
assert.equal(timers.size, 0, "successful completion stops polling");

context.openDirectorySync({...source, pending_mode: "preview"});
context.closeDirectorySync();
assert.equal(timers.size, 0, "closing cancels a scheduled poll");
context.openDirectorySync({...source, running: true});
tick();
const stale = requests.shift();
context.closeDirectorySync();
context.openDirectorySync({...source, id: 2});
stale.success({...source, running: true});
assert.equal(vm.runInContext("directorySyncSource.id", context), 2);
assert.equal(timers.size, 0, "a late response cannot restart polling for a closed source");
stale.failure({status: 503});
assert.equal(errors.length, 0, "ignore errors from a closed source");

context.openDirectorySync({...source, running: true});
context.location.pathname = "/teams";
tick();
assert.equal(requests.length, 0, "navigation away stops status requests");
assert.equal(timers.size, 0);
context.location.pathname = "/admin/directory-sync";
context.openDirectorySync({...source, running: true});
tick();
for (let attempt = 0; attempt < 5; attempt++) {
    if (attempt) tick();
    requests.shift().failure({status: 503, responseJSON: {message: "Service unavailable"}});
    assert.equal(context.$("#ds-workflow").attr("data-step"), attempt < 4 ? "retrying" : "disconnected");
    assert.equal(context.$("#ds-run").prop("loading"), false, "unknown state must not look like running forever");
}
assert.equal(errors.length, 1, "surface the final failure without repeated error popups");
assert.equal(timers.size, 0, "stop automatic retries after five failed reads");
assert.equal(context.$("#ds-refresh-status").prop("hidden"), false, "offer explicit status recovery");
assert.equal(context.$("#ds-run").prop("disabled"), true, "do not allow a duplicate operation while state is unknown");
handlers.get("#ds-refresh-status")();
tick();
requests.shift().success(source);
assert.equal(context.$("#ds-workflow").attr("data-step"), "saved");
assert.equal(context.$("#ds-refresh-status").prop("hidden"), true);
assert.equal(timers.size, 0, "manual status recovery completes without resubmitting work");

for (const action of ["preview", "apply"]) {
    context.openDirectorySync({...source, approved: false, pending_mode: action});
    tick();
    requests.shift().failure({status: 500});
    assert.equal(context.$("#ds-workflow").attr("data-step"), "retrying");
    assert.equal(context.$("#ds-" + action).prop("loading"), false);
    tick();
    const completed = action === "preview"
        ? {...source, approved: false, preview_token: "ready", preview_until: new Date(Date.now() + 60000).toISOString()}
        : source;
    requests.shift().success(completed);
    assert.equal(context.$("#ds-workflow").attr("data-step"), action === "preview" ? "apply" : "saved");
    assert.equal(context.$("#ds-apply").prop("disabled"), action !== "preview");
    assert.equal(context.$("#ds-refresh-status").prop("hidden"), true);
    context.closeDirectorySync();
    assert.equal(timers.size, 0);
}

for (const status of [401, 403, 404]) {
    context.openDirectorySync({...source, pending_mode: "preview"});
    tick();
    requests.shift().failure({status});
    assert.equal(timers.size, 0, "do not retry permanent access/deletion failures");
    assert.equal(context.$("#ds-workflow").attr("data-step"), "disconnected");
}

context.openDirectorySync({...source, approved: false, pending_mode: "preview"});
tick();
requests.shift().success({...source, approved: false, last_error: "Preview could not load schedules"});
assert.equal(context.$("#ds-workflow").attr("data-step"), "error");
assert.equal(context.$("#ds-workflow-detail").value, "Preview could not load schedules");
assert.equal(context.$("#ds-preview").prop("disabled"), false, "failed preview can be retried");
assert.equal(context.$("#ds-apply").prop("disabled"), true);
context.openDirectorySync({...source, current_error: "One schedule has an unsupported status"});
assert.equal(context.$("#ds-workflow").attr("data-step"), "current_error");
assert.equal(context.$("#ds-workflow-detail").value, "One schedule has an unsupported status");
console.log("Directory polling retries, recovery, failure feedback and cancellation passed");
