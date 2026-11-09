"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const elements = new Map();
const requests = [];
const errors = [];
const context = {
    window: {}, currentUser: null,
    asArray: value => Array.isArray(value) ? value : [],
    $: selector => {
        if (!elements.has(selector)) {
            elements.set(selector, {
                length: 1, value: "", hidden: false, disabled: false,
                val() { return this.value; },
                toggleClass(name, hidden) { this.hidden = hidden; return this; },
                prop(name, value) { this[name] = value; return this; },
            });
        }
        return elements.get(selector);
    },
    apiGet: (url, success, failure) => requests.push({url, success, failure}),
    showApiError: error => errors.push(error),
};
vm.createContext(context);
for (const file of ["rbac_roles.js", "selects.js"]) {
    vm.runInContext(fs.readFileSync(path.join(root, "app/static/js/core", file), "utf8"), context);
}

function user(role = "viewer", groupId = 10) {
    return {id: 1, is_admin: false, active_group_id: groupId,
        groups: [{id: 99, group_id: groupId, active: true, role}]};
}

function team(write, resources = write, extra = {}) {
    return {id: 20, group_id: 10, active: true,
        permissions: {can_write: write, can_write_resources: resources}, ...extra};
}

function load(teams) {
    context.setCurrentUserUiTeams(teams, context.currentUser, context.getCurrentUserActiveGroupId());
}

function button(name, allowed) {
    const element = elements.get("#open-" + name + "-create-modal");
    assert.equal(element.hidden, !allowed, name + " visibility");
    assert.equal(element.disabled, !allowed, name + " enabled");
}

const strictObjects = ["rotation", "escalation-policy", "notification-policy", "priority-policy", "matcher-preset"];
const resources = ["route", "channel", "silence"];
context.currentUser = user();
assert.equal(context.currentUserCanCreateUiObjects(), false, "wait for authoritative permissions");
load([team(false), team(true)]);
for (const name of [...strictObjects, ...resources]) button(name, true);
button("team", false);
assert.equal(context.canWriteObject({permissions: {can_write: true}}), true, "editing remains permitted");

for (const role of ["viewer", "responder"]) {
    load([team(false, false, {current_user_role: role})]);
    for (const name of [...strictObjects, ...resources, "team"]) button(name, false);
}

context.currentUser = user("editor");
load([team(false, true)]);
for (const name of strictObjects) button(name, false);
for (const name of [...resources, "team"]) button(name, true);

context.currentUser = user("user_admin");
load([team(true)]);
for (const name of [...strictObjects, ...resources, "team"]) button(name, true);
context.currentUser = {...user(), is_admin: true};
load([team(true)]);
for (const name of [...strictObjects, ...resources, "team"]) button(name, true);

context.currentUser = user();
load([team(true, true, {active: false})]);
assert.equal(context.currentUserCanCreateUiObjects(), false, "inactive teams cannot enable creation");
load([team(false, false, {current_user_role: "manager"}), {id: 21, role: "manager"}]);
assert.equal(context.currentUserCanCreateUiObjects(), false, "missing or denied capabilities stay denied");
load([]);
assert.equal(context.currentUserCanCreateUiObjects(), false, "empty groups have no create target");

// Old responses must not restore permissions after an active-group switch,
// including switching away and back to the same group.
let oldCallbacks = 0;
context.loadUiTeams(() => oldCallbacks++);
const stale = requests.pop();
assert.equal(stale.url, "/api/teams");
context.currentUser = user("viewer", 11);
context.applyCreateButtonsVisibility();
for (const name of [...strictObjects, ...resources]) button(name, false);
stale.success([team(true)]);
assert.equal(oldCallbacks, 0);
assert.equal(context.currentUserCanCreateUiObjects(), false);
context.currentUser = user();
stale.success([team(true)]);
assert.equal(oldCallbacks, 0);

context.loadUiTeams(() => {});
requests.pop().success([team(true)]);
assert.equal(context.currentUserCanCreateUiObjects(), true);
context.currentUser.active_group_id = 11;
assert.equal(context.currentUserCanCreateUiObjects(), false, "scope changes invalidate cached permissions");
context.currentUser = user();

let received;
context.loadUiTeams(teams => { received = teams; });
requests.pop().failure({status: 503});
assert.equal(received.length, 0);
assert.equal(errors.length, 1, "load errors must remain visible");
assert.equal(context.currentUserCanCreateUiObjects(), false);
context.loadUiTeams(teams => { received = teams; });
requests.pop().success([team(true)]);
assert.equal(received.length, 1);
assert.equal(context.currentUserCanCreateUiObjects(), true, "retry restores creation");
stale.failure({status: 403});
assert.equal(errors.length, 1, "ignore errors belonging to an old user scope");
assert.equal(context.currentUserCanCreateUiObjects(), true);
console.log("Team creation permissions, scope changes and retries passed");
