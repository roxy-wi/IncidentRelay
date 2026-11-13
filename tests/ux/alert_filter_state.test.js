"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const source = fs.readFileSync(path.resolve(__dirname, "../../app/static/js/core/alert_filter_state.js"), "utf8");

function browser(storage = new Map()) {
    let blocked = false;
    const context = {
        currentUser: {id: 10, active_group_id: 1}, URLSearchParams,
        window: {location: new URL("https://ir.example/")},
        console: {warn() {}},
        localStorage: {
            getItem(key) { return storage.get(key) || null; },
            setItem(key, value) { if (blocked) throw new Error("Quota exceeded"); storage.set(key, value); }
        },
        history: {state: null, replaceState(state, unused, url) {
            this.state = state;
            context.window.location = new URL(url, "https://ir.example");
        }}
    };
    vm.runInNewContext(source, context);
    return {state: context.window.AlertFilterState, context, storage,
        blockWrites() { blocked = true; },
        go(url, state = null) { context.window.location = new URL(url, "https://ir.example"); context.history.state = state; }};
}

test("common filters persist across pages and reloads; inbox fields stay in Alerts", () => {
    const b = browser();
    b.state.remember("dashboard", new URLSearchParams("involvement=any&service_id=4&service_id=5&team=1"));
    b.go("/alerts?team=2");
    let params = b.state.resolve("alerts");
    assert.equal(params.get("involvement"), "any");
    assert.deepEqual(params.getAll("service_id"), ["4", "5"]);
    assert.equal(params.get("team"), "2");
    params.set("status", "resolved");
    params.set("involvement", "responder");
    b.state.remember("alerts", params);
    const reloaded = browser(b.storage);
    params = reloaded.state.resolve("dashboard");
    assert.equal(params.get("involvement"), "responder");
    assert.equal(params.has("status"), false);
    reloaded.go("/alerts?team=3");
    params = reloaded.state.resolve("alerts");
    assert.equal(params.get("status"), "resolved");
    assert.equal(params.get("team"), "3");
});

test("explicit URLs and reset history entries win over saved preferences", () => {
    const b = browser();
    b.state.remember("dashboard", new URLSearchParams("involvement=any&service_id=4"));
    b.go("/alerts?status=resolved");
    assert.equal(b.state.resolve("alerts").toString(), "status=resolved");
    b.go("/?team=1");
    b.state.remember("dashboard", new URLSearchParams("team=1"));
    const resetEntry = b.context.history.state;
    b.state.remember("dashboard", new URLSearchParams("involvement=stakeholder&team=1"));
    b.go("/?team=1", resetEntry);
    assert.equal(b.state.resolve("dashboard").toString(), "team=1");
    b.state.remember("dashboard", new URLSearchParams("team=1"));
    b.go("/alerts?team=1");
    assert.equal(b.state.resolve("alerts").has("involvement"), false);
});

test("preferences are isolated by user and active group", () => {
    const b = browser();
    b.state.remember("dashboard", new URLSearchParams("involvement=any&service_id=4"));
    b.context.currentUser.active_group_id = 2;
    b.go("/");
    assert.equal(b.state.resolve("dashboard").toString(), "");
    b.context.currentUser = {id: 11, active_group_id: 1};
    b.go("/");
    assert.equal(b.state.resolve("dashboard").toString(), "");
    b.context.currentUser = {id: 10, active_group_id: 1};
    b.go("/");
    assert.equal(b.state.resolve("dashboard").get("involvement"), "any");
});

test("failed storage writes keep current preferences and inactive pages cannot write", () => {
    const b = browser();
    b.state.remember("dashboard", new URLSearchParams("involvement=any"));
    b.blockWrites();
    b.state.remember("dashboard", new URLSearchParams("involvement=responder"));
    b.go("/alerts?team=1");
    assert.equal(b.state.resolve("alerts").get("involvement"), "responder");
    const before = b.context.window.location.href;
    b.state.remember("dashboard", new URLSearchParams("involvement=stakeholder"));
    assert.equal(b.context.window.location.href, before);
    assert.equal(b.state.saved("dashboard").get("involvement"), "responder");
});
