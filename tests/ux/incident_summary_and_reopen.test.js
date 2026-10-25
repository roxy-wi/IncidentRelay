"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");

function extractFunction(file, name, nextName) {
    const source = fs.readFileSync(path.join(root, file), "utf8");
    const start = source.indexOf("function " + name + "(");
    const end = source.indexOf("\nfunction " + nextName + "(", start);
    assert(start >= 0 && end > start, "function " + name + " is present");
    return source.substring(start, end);
}

function testSummaryUsesOneScope() {
    const labels = {};
    const urls = [];
    const context = {
        URLSearchParams,
        incidentsLoadGeneration: 4,
        incidentSelectedTeamId: () => 11,
        $: selector => ({text: value => {labels[selector] = value;}}),
        apiGet: (url, success) => {
            urls.push(url);
            const p = new URLSearchParams(url.split("?")[1]);
            assert.equal(p.get("team_id"), "11");
            assert.equal(p.get("page_size"), "1");
            assert.equal(p.get("search"), null);
            const counts = {"": 16, resolved: 3, closed: 2, cancelled: 1};
            success({pagination: {total: counts[p.get("status") || ""]}});
        },
    };
    vm.createContext(context);
    vm.runInContext(extractFunction("app/static/js/pages/incidents.js", "loadIncidentsSummary", "loadIncidentCreatePermissions"), context);
    context.loadIncidentsSummary(4);
    assert.equal(urls.length, 4);
    assert.equal(labels["#incidents-summary-total"], 16);
    assert.equal(labels["#incidents-summary-active"], 10);
    assert.equal(labels["#incidents-summary-resolved"], 3);
    assert.equal(labels["#incidents-summary-closed"], 2);
}

function testSummaryIgnoresStaleAsyncResults() {
    const labels = {};
    const callbacks = [];
    const context = {
        URLSearchParams,
        incidentsLoadGeneration: 5,
        incidentSelectedTeamId: () => null,
        $: selector => ({text: value => {labels[selector] = value;}}),
        apiGet: (url, success) => {callbacks.push(success);},
    };
    vm.createContext(context);
    vm.runInContext(extractFunction("app/static/js/pages/incidents.js", "loadIncidentsSummary", "loadIncidentCreatePermissions"), context);
    context.loadIncidentsSummary(5);
    context.incidentsLoadGeneration = 6;
    callbacks.forEach(cb => cb({pagination: {total: 100}}));
    assert.equal(labels["#incidents-summary-active"], "—");
}

function testChildNavigationUsesItsOwnTabAndOccurrenceId() {
    const calls = [];
    const item = {
        length: 1,
        0: {scrollIntoView: value => calls.push("scroll:" + value.block)},
        attr: (name) => name === "data-child-alert-id" ? "42" : null,
        addClass: name => {calls.push("add:" + name); return item;},
        trigger: name => {calls.push("trigger:" + name); return item;},
        first: () => item,
    };
    const collection = {
        filter: predicate => predicate.call(item) ? item : {length: 0},
        removeClass: name => {calls.push("remove:" + name);},
    };
    const modal = {
        find: selector => selector.includes("#alert-group-children") ? collection : collection,
    };
    const context = {
        alertDetailsModal: () => modal,
        setAlertDetailsTab: name => calls.push("tab:" + name),
        $: obj => obj,
    };
    vm.createContext(context);
    vm.runInContext(extractFunction("app/static/js/pages/alerts.js", "focusAlertChildOccurrence", "alertEventTypeLabel"), context);
    context.focusAlertChildOccurrence(42);
    assert(calls.includes("tab:alerts"));
    assert(calls.includes("add:is-highlighted"));
    assert(calls.includes("trigger:focus"));
    assert(calls.includes("scroll:nearest"));
    calls.length = 0;
    context.focusAlertChildOccurrence(-1);
    assert.equal(calls.length, 0);
}

testSummaryUsesOneScope();
testSummaryIgnoresStaleAsyncResults();
testChildNavigationUsesItsOwnTabAndOccurrenceId();
console.log("Incident summary and reopen UX contracts passed");
