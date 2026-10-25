"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
function segment(file, from, to) {
    const src = fs.readFileSync(path.join(root, file), "utf8");
    const a = src.indexOf("function " + from + "(");
    const b = src.indexOf("\nfunction " + to + "(", a);
    assert(a >= 0 && b > a, from);
    return src.slice(a, b);
}
const context = {currentUser: {is_admin: false, groups: [
    {id: 6, group_id: 2, active: true, role: "user_admin"},
    {id: 7, group_id: 6, active: true, role: "viewer"},
]}, asArray: x => Array.isArray(x) ? x : []};
vm.createContext(context);
vm.runInContext(segment("app/static/js/core/rbac_roles.js", "getCurrentUserGroupRole", "canEditGroup"), context);
assert.equal(context.getCurrentUserGroupRole(2), "user_admin");
assert.equal(context.getCurrentUserGroupRole(6), "viewer");
assert.equal(context.getCurrentUserGroupRole(7), null);
const admin = segment("app/static/js/pages/admin_users.js", "canManageGroupId", "applyAdminUserFormPermissions");
context.isGlobalAdminUser = () => false;
context.GROUP_USER_ADMIN_ROLE = "user_admin";
vm.runInContext(admin, context);
assert.equal(context.canManageGroupId(2), true);
assert.equal(context.canManageGroupId(6), false);
assert.equal(context.canManageGroupId(7), false);
console.log("Strict membership resource identities passed");
