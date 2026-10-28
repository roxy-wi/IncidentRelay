"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app/static/js/pages/incidents.js", "utf8");
const requests = [];
const rendered = [];
const errors = [];
const elements = new Map();
function $(selector) {
    if (elements.has(selector)) { return elements.get(selector); }
    const values = {};
    const element = {};
    for (const method of ["on", "addClass", "removeClass", "toggleClass", "empty", "append"]) {
        element[method] = () => element;
    }
    element.val = value => value === undefined ? values.value : (values.value = value, element);
    element.text = value => value === undefined ? values.text : (values.text = value, element);
    element.prop = (key, value) => value === undefined ? values[key] : (values[key] = value, element);
    elements.set(selector, element);
    return element;
}
$.extend = Object.assign;
$.trim = value => value.trim();
const context = {
    $, document: {}, URL, URLSearchParams,
    window: {location: {pathname: "/incidents/1", search: "", origin: "http://localhost"}},
    i18n: {t: key => key},
    apiGet: (url, ok, fail) => requests.push({url, ok, fail}),
    apiRequest: (method, url, payload, ok, fail) => requests.push({method, url, payload, ok, fail}),
    showApiError: xhr => errors.push(xhr),
    getApiErrorMessage: xhr => xhr.responseJSON.message,
    history: {pushState: () => {}, replaceState: () => {}},
    appUrlWithGlobalTeamScope: path => path,
};
vm.createContext(context);
vm.runInContext(source, context);
context.renderIncidentDetails = incident => rendered.push(incident.id);
context.loadIncidentDetailCollections = () => {};
const incident = id => ({id, permissions: {can_respond: true}});

// An older success cannot replace a newer Incident or refresh.
context.loadIncidentDetails(1);
context.window.location.pathname = "/incidents/2";
context.loadIncidentDetails(2);
requests[1].ok(incident(2));
requests[0].ok(incident(1));
assert.deepEqual(rendered, [2]);
context.loadIncidentDetails(2);
context.loadIncidentDetails(2);
requests[3].ok(incident(2));
requests[2].fail({responseJSON: {message: "stale failure"}});
assert.deepEqual(errors, []);

// Router and list callbacks must not launch duplicate detail loads.
const before = requests.length;
context.syncIncidentDetailsFromUrl();
assert.equal(requests.length, before);
context.window.location.pathname = "/incidents/3";
context.syncIncidentDetailsFromUrl();
context.syncIncidentDetailsFromUrl();
assert.equal(requests.length, before + 1);
context.closeIncidentDetails({updateUrl: false});
context.window.location.pathname = "/incidents";
requests.at(-1).ok(incident(3));
assert.equal(vm.runInContext("currentIncident", context), null);

// Detail and list URLs preserve filters through navigation and reload.
context.window.location.search = "?search=cpu%20high&status=resolved&page=3&page_size=50";
assert.equal(context.buildIncidentDetailsUrl(7), "/incidents/7?search=cpu+high&status=resolved&page=3&page_size=50");
context.restoreIncidentListFilters();
assert.equal($("#incidents-search").val(), "cpu high");
assert.equal(vm.runInContext("incidentsCurrentPage", context), 3);

// Failed saves retain draft text and do not automatically load/overwrite it.
context.window.location.pathname = "/incidents/7";
context.loadIncidentDetails(7);
requests.at(-1).ok(incident(7));
$("#incident-root-cause").val("unsaved draft");
context.mutateIncident("PATCH", "", {row_version: 1, root_cause: "unsaved draft"});
const save = requests.at(-1);
const count = requests.length;
save.fail({status: 409, responseJSON: {message: "conflict"}});
assert.equal(requests.length, count);
assert.equal($("#incident-root-cause").val(), "unsaved draft");
assert.equal($("#incident-resolution-save").prop("disabled"), false);
assert.equal($("#incident-details-error").text(), "incidents.workspace.conflict");
console.log("Workspace navigation and conflict regressions passed");
