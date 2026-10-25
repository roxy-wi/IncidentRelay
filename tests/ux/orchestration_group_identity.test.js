"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");

function extractFunction(filename, name, nextName) {
    const src = fs.readFileSync(path.join(root, filename), "utf8");
    const start = src.indexOf("function " + name + "(");
    const end = src.indexOf("\nfunction " + nextName + "(", start);
    assert.ok(start >= 0 && end > start, name + " must be present");
    return src.slice(start, end);
}

const groupSelection = extractFunction(
    "app/static/js/pages/orchestrations.js", "orchestrationGroupId", "orchestrationClone"
);
const groupRole = extractFunction(
    "app/static/js/core/rbac_roles.js", "getCurrentUserGroupRole", "canEditGroup"
);

function scope(user, selectedGroupId = "") {
    const context = {
        currentUser: user,
        asArray: value => Array.isArray(value) ? value : [],
        $: selector => {
            assert.equal(selector, "#active-group-select");
            return {val: () => selectedGroupId};
        },
    };
    vm.createContext(context);
    vm.runInContext(groupSelection + "\n" + groupRole, context);
    return context;
}

// Membership id 6 and group id 2 must never be confused.
const membership = {id: 6, group_id: 2, role: "user_admin", active: true};
const user = {is_admin: false, active_group_id: null, groups: [membership]};
assert.equal(scope(user).orchestrationGroupId(), 2);
assert.equal(scope(user).getCurrentUserGroupRole(2), "user_admin");
assert.equal(scope(user).getCurrentUserGroupRole(6), null);

// Explicit active choice and persisted active group keep their precedence.
assert.equal(scope({...user, active_group_id: 3}, "4").orchestrationGroupId(), 4);
assert.equal(scope({...user, active_group_id: 3}).orchestrationGroupId(), 3);
assert.equal(scope({...user, groups: []}).orchestrationGroupId(), null);

// Prevent false-positive permissions if a membership id equals another group id.
const second = {id: 7, group_id: 6, role: "viewer", active: true};
assert.equal(
    scope({...user, groups: [membership, second]}).getCurrentUserGroupRole(6),
    "viewer"
);

// Synthetic admin profile groups carry group_id even without a membership id.
assert.equal(
    scope({is_admin: true, active_group_id: null, groups: [
        {id: null, group_id: 9, role: "admin", active: true},
    ]}).orchestrationGroupId(),
    9
);

console.log("Orchestration group ID and group role identity regression passed");
