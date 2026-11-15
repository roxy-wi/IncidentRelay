"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
const timers = new Map();
const requests = [];
const errors = [];
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
            const element = {value: ""};
            for (const name of ["on", "prop", "empty", "append", "scrollTop", "trigger"]) {
                element[name] = () => element;
            }
            element.val = value => { element.value = value; return element; };
            element.text = value => { element.value = value; return element; };
            elements.set(selector, element);
        }
        return elements.get(selector);
    },
};
context.AppLoading = {
    clear: selector => context.$(selector).text(""),
    showBlock: (selector, message) => context.$(selector).text(message),
    setButtonLoading() {},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("app/static/js/pages/directory_sync.js", "utf8"), context);
vm.runInContext("directorySyncOptions = {preset: {}, groups: [], teams: []}", context);
context.dsRenderResult = source => context.$("#ds-status").text(source?.last_error || source?.current_error || "");
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
requests.shift().failure({status: 503, responseJSON: {message: "Service unavailable"}});
assert.equal(errors.length, 1, "surface a failed status request");
assert.equal(timers.size, 0, "failed status requests do not retry indefinitely");
console.log("Directory status polling, completion errors and cancellation passed");
