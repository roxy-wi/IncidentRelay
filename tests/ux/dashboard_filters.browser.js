"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const f = JSON.parse(process.env.DASHBOARD_FILTERS_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const context = await browser.newContext({baseURL: f.baseUrl, viewport: {width: 1440, height: 1080}, serviceWorkers: "block"});
    await context.addCookies([{name: "incidentrelay_jwt", value: f.token, url: f.baseUrl},
        {name: "incidentrelay_locale", value: "en", url: f.baseUrl}]);
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => new URL(route.request().url()).origin === f.baseUrl ? route.continue() : route.abort());
    const all = [f.assigned, f.responder, f.stakeholder, f.unrelated];
    const mine = [f.assigned, f.responder, f.stakeholder];
    async function dashboardRows(ids) {
        await page.waitForFunction(expected => {
            const rows = [...document.querySelectorAll("#dashboard-alerts .overview-id-link")].map(el => Number(el.textContent.slice(1))).sort((a, b) => a - b);
            return JSON.stringify(rows) === JSON.stringify(expected.slice().sort((a, b) => a - b))
                && !document.querySelector('#dashboard-alerts [role="status"], #dashboard-alerts [role="alert"]');
        }, ids);
    }
    async function setService(value) {
        await page.evaluate(value => document.querySelector("#dashboard-service-filter").tomselect.setValue(value), String(value));
    }
    async function chooseInvolvement(value, id = "dashboard-involvement-filter") {
        const wrapper = page.locator(".ts-wrapper").filter({has: page.locator("#" + id + "-ts-control")});
        await wrapper.locator(".ts-control").click();
        await wrapper.locator('.ts-dropdown [data-value="' + value + '"]').click();
    }
    async function assertMatchingFilterStyle(involvementId, serviceId) {
        const styles = await page.evaluate(ids => ids.map(id => {
            const picker = document.getElementById(id).tomselect;
            if (!picker) return null;
            const style = getComputedStyle(picker.control);
            return [style.borderRadius, style.borderWidth, style.borderColor,
                style.backgroundColor, style.minHeight, style.fontFamily, style.fontSize];
        }), [involvementId, serviceId]);
        assert.notEqual(styles[0], null, "involvement must use the shared filter component");
        assert.deepEqual(styles[0], styles[1], "new and existing filters must share their appearance");
        assert.equal(await page.evaluate(id => document.getElementById(id).tomselect.settings.maxItems, involvementId), 1);
    }
    async function openFilters() {
        if (await page.locator("#dashboard-toggle-filters").getAttribute("aria-expanded") !== "true") {
            await page.locator("#dashboard-toggle-filters").click();
        }
    }
    async function alertsRows(ids) {
        await page.waitForFunction(expected => {
            const ids = [...document.querySelectorAll("#alerts-table .alerts-id-link")]
                .map(el => Number(el.textContent.slice(1))).sort((a, b) => a - b);
            return location.pathname === "/alerts" && JSON.stringify(ids) === JSON.stringify(expected.slice().sort((a, b) => a - b));
        }, ids);
    }
    async function menu(pathname) {
        await page.locator('.menu-link[data-page][href="' + pathname + '"]').click();
    }
    try {
        await page.goto(`/alerts?team=${f.team}&assigned_to_me=true&status=firing`);
        await page.waitForFunction(id => typeof alertsCache !== "undefined" && alertsCache.length === 1 && alertsCache[0].id === id, f.assigned);
        assert.equal(await page.locator("#alerts-involvement-filter").inputValue(), "assigned", "legacy bookmarks retain assignment filtering");
        await assertMatchingFilterStyle("alerts-involvement-filter", "alerts-service-filter");
        await page.goto("/?team=" + f.team);
        await dashboardRows([f.assigned]);
        await page.reload();
        await dashboardRows([f.assigned]);
        await page.locator("#dashboard-reset-filters").click();
        await dashboardRows(all);
        assert.equal(await page.locator("#dashboard-alert-filters").isVisible(), false);
        await page.waitForFunction(() => dashboardHasLoaded && dashboardImpactHasLoaded);
        const overview = await page.evaluate(() => ({generation: dashboardLoadGeneration, impact: dashboardImpactLoadGeneration,
            summary: document.querySelector("#overview-alerts-summary").textContent, system: document.querySelector("#dashboard-system-status").textContent}));
        await page.locator("#dashboard-my-alerts").click();
        await dashboardRows(mine);
        assert.deepEqual(await page.evaluate(() => ({generation: dashboardLoadGeneration, impact: dashboardImpactLoadGeneration,
            summary: document.querySelector("#overview-alerts-summary").textContent, system: document.querySelector("#dashboard-system-status").textContent})), overview,
        "personal filters must not reload or alter global widgets");
        await openFilters();
        await assertMatchingFilterStyle("dashboard-involvement-filter", "dashboard-service-filter");
        await setService(f.service);
        await dashboardRows(mine);
        await page.screenshot({path: path.join(f.screenshots, "desktop.png"), fullPage: true});
        await page.locator(".ts-wrapper").filter({has: page.locator("#dashboard-involvement-filter-ts-control")}).locator(".ts-control").click();
        await page.locator("#dashboard-involvement-filter-ts-dropdown").waitFor({state: "visible"});
        assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector("#dashboard-involvement-filter").tomselect.control).borderColor),
            await page.locator("#dashboard-my-alerts").evaluate(el => getComputedStyle(el).backgroundColor));
        await page.locator(".dashboard-area-active").screenshot({path: path.join(f.screenshots, "filters-desktop.png")});
        await page.keyboard.press("Escape");
        await page.locator("#dashboard-toggle-filters").focus();
        await page.evaluate(() => { document.documentElement.dataset.colorScheme = "dark"; });
        await assertMatchingFilterStyle("dashboard-involvement-filter", "dashboard-service-filter");
        await page.locator(".dashboard-area-active").screenshot({path: path.join(f.screenshots, "filters-dark.png")});
        await page.evaluate(() => { document.documentElement.dataset.colorScheme = "light"; });

        // Common filters follow menu navigation in both directions and survive reloads.
        await menu("/alerts");
        await alertsRows(mine);
        assert.equal(await page.locator("#alerts-involvement-filter").inputValue(), "any");
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#alerts-service-filter")), [String(f.service)]);
        await chooseInvolvement("stakeholder", "alerts-involvement-filter");
        await alertsRows([f.stakeholder]);
        await page.reload();
        await alertsRows([f.stakeholder]);
        await menu("/");
        await dashboardRows([f.stakeholder]);
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#dashboard-service-filter")), [String(f.service)]);
        await menu("/alerts");
        await alertsRows([f.stakeholder]);
        await chooseInvolvement("assigned", "alerts-involvement-filter");
        await alertsRows([f.assigned]);
        await page.evaluate(() => document.querySelector("#status-filter").tomselect.setValue(["resolved"]));
        await alertsRows([f.resolved]);
        await menu("/");
        await dashboardRows([f.assigned]);
        await menu("/alerts");
        await alertsRows([f.resolved]);
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#status-filter")), ["resolved"], "menu links carrying only team must retain inbox filters");
        await page.evaluate(() => document.querySelector("#status-filter").tomselect.setValue(["firing"]));
        await alertsRows([f.assigned]);

        // An Alerts response finishing after navigation must not rewrite Dashboard's URL.
        let releaseInbox;
        const inboxGate = new Promise(resolve => { releaseInbox = resolve; });
        await page.route("**/api/alert-groups?*", async route => {
            const params = new URL(route.request().url()).searchParams;
            if (params.get("involvement") === "responder" && params.get("page_size") === "25") await inboxGate;
            return route.continue();
        });
        const pendingInbox = page.waitForRequest(r => new URL(r.url()).pathname === "/api/alert-groups"
            && new URL(r.url()).searchParams.get("involvement") === "responder"
            && new URL(r.url()).searchParams.get("page_size") === "25");
        const lateInbox = page.waitForResponse(r => new URL(r.url()).pathname === "/api/alert-groups"
            && new URL(r.url()).searchParams.get("involvement") === "responder"
            && new URL(r.url()).searchParams.get("page_size") === "25");
        await chooseInvolvement("responder", "alerts-involvement-filter");
        await pendingInbox;
        await menu("/");
        await dashboardRows([f.responder]);
        const dashboardUrl = page.url();
        releaseInbox();
        await (await lateInbox).finished();
        await page.unroute("**/api/alert-groups?*");
        assert.equal(page.url(), dashboardUrl);
        await menu("/incidents");
        await page.goBack();
        await dashboardRows([f.responder]);
        await page.goForward();
        await page.waitForURL("**/incidents*");
        await menu("/");
        await dashboardRows([f.responder]);
        await openFilters();

        for (const [involvement, ids] of [["responder", [f.responder]], ["stakeholder", [f.stakeholder]], ["any", mine], ["assigned", [f.assigned]]]) {
            if (await page.locator("#dashboard-involvement-filter").inputValue() === involvement) {
                await chooseInvolvement("any");
                await dashboardRows(mine);
            }
            await chooseInvolvement(involvement);
            await dashboardRows(ids);
            const href = new URL(await page.locator("#dashboard-view-alerts").getAttribute("href"), f.baseUrl);
            assert.equal(href.searchParams.get("involvement"), involvement);
            assert.equal(href.searchParams.get("service_id"), String(f.service));
            assert.equal(href.searchParams.get("team"), String(f.team));
            assert.deepEqual(href.searchParams.getAll("status"), ["firing", "acknowledged"]);
            await page.locator("#dashboard-view-alerts").click();
            await page.waitForURL("**/alerts?*");
            await page.waitForFunction(expected => JSON.stringify(alertsCache.map(row => row.id).sort((a, b) => a - b)) === JSON.stringify(expected.slice().sort((a, b) => a - b)), ids);
            assert.equal(await page.locator("#alerts-involvement-filter").inputValue(), involvement);
            assert.equal(new URL(page.url()).searchParams.get("involvement"), involvement);
            assert.equal(await page.locator("#alerts-table .alerts-row").count(), ids.length);
            if (involvement === "assigned") {
                await page.evaluate(() => openAlertAnalyticsInboxSearch("Unrelated alert"));
                await page.waitForFunction(id => alertsCache.length === 1 && alertsCache[0].id === id, f.unrelated);
                assert.equal(await page.locator("#alerts-involvement-filter").inputValue(), "", "analytics drill-down clears personal filters");
            }
            await page.goBack();
            await dashboardRows(ids);
            await openFilters();
        }

        // Empty selection and reset restore the active (not resolved) inbox.
        await setService(f.emptyService);
        await page.getByText("No active alerts match these filters.", {exact: true}).waitFor();
        await page.locator("#dashboard-reset-filters").click();
        await dashboardRows(all);
        assert.equal(await page.locator("#dashboard-all-alerts").getAttribute("aria-pressed"), "true");
        assert.equal(await page.evaluate(() => document.querySelector("#dashboard-involvement-filter").tomselect.control.textContent.trim()), "All alerts");
        assert.equal(new URL(page.url()).searchParams.has("service_id"), false);
        await menu("/alerts");
        await alertsRows([f.unrelated]);
        assert.equal(await page.locator("#alerts-involvement-filter").inputValue(), "");
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#alerts-service-filter")), []);
        await menu("/");
        await dashboardRows(all);
        await page.reload();
        await dashboardRows(all);
        await openFilters();

        // A failed personal request must replace the old All alerts table.
        await page.route("**/api/alert-groups?*", route => {
            if (new URL(route.request().url()).searchParams.get("involvement") === "any") {
                return route.fulfill({status: 500, contentType: "application/json", body: JSON.stringify({error: "test failure"})});
            }
            return route.continue();
        });
        await page.locator("#dashboard-my-alerts").click();
        await page.locator('#dashboard-alerts [role="alert"]').waitFor();
        assert.equal(await page.locator("#dashboard-alerts .overview-id-link").count(), 0);
        assert.equal(await page.locator("#overview-alerts-summary").textContent(), overview.summary);
        await page.locator("#app-dialog-confirm").click();
        await page.unroute("**/api/alert-groups?*");
        await page.locator("#reload-dashboard").click();
        await dashboardRows(mine);

        // A late response for a previous filter must not replace the latest one.
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        await page.route("**/api/alert-groups?*", async route => {
            if (new URL(route.request().url()).searchParams.get("involvement") === "responder") await gate;
            return route.continue();
        });
        const pendingRequest = page.waitForRequest(r => new URL(r.url()).searchParams.get("involvement") === "responder");
        const lateResponse = page.waitForResponse(r => new URL(r.url()).searchParams.get("involvement") === "responder");
        await chooseInvolvement("responder");
        await pendingRequest;
        await chooseInvolvement("stakeholder");
        await dashboardRows([f.stakeholder]);
        release();
        await (await lateResponse).finished();
        await page.unroute("**/api/alert-groups?*");
        await dashboardRows([f.stakeholder]);

        // Team change refreshes service options and drops incompatible IDs.
        await page.locator("#dashboard-all-alerts").click();
        await dashboardRows(all);
        await setService(f.service);
        await dashboardRows(all);
        let releaseServices;
        const serviceGate = new Promise(resolve => { releaseServices = resolve; });
        await page.route("**/api/services?*", async route => {
            if (new URL(route.request().url()).searchParams.get("team_id") === String(f.otherTeam)) await serviceGate;
            return route.continue();
        });
        const serviceRequest = page.waitForRequest(r => new URL(r.url()).pathname === "/api/services"
            && new URL(r.url()).searchParams.get("team_id") === String(f.otherTeam));
        const lateServices = page.waitForResponse(r => new URL(r.url()).pathname === "/api/services"
            && new URL(r.url()).searchParams.get("team_id") === String(f.otherTeam));
        await page.locator("#global-team-filter").selectOption(String(f.otherTeam));
        await serviceRequest;
        await page.locator("#global-team-filter").selectOption(String(f.team));
        await dashboardRows(all);
        releaseServices();
        await (await lateServices).finished();
        await page.unroute("**/api/services?*");
        await dashboardRows(all);
        assert.equal(await page.evaluate(() => document.querySelector("#dashboard-service-filter").tomselect.isDisabled), false);
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#dashboard-service-filter")), [String(f.service)]);
        assert.equal(await page.evaluate(id => !!document.querySelector("#dashboard-service-filter").tomselect.options[id], f.otherService), false,
            "late service responses must not restore another team's options");
        await page.locator("#global-team-filter").selectOption(String(f.otherTeam));
        await dashboardRows([f.other]);
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#dashboard-service-filter")), []);
        assert.equal(new URL(page.url()).searchParams.has("service_id"), false);
        assert.deepEqual(await page.evaluate(() => Object.keys(document.querySelector("#dashboard-service-filter").tomselect.options)), [String(f.otherService)]);

        // Same "all teams" cache key still differs between authorization groups.
        await page.locator("#global-team-filter").selectOption("");
        await dashboardRows([...all, f.other]);
        await setService(f.service);
        await dashboardRows(all);
        await page.locator("#topbar-profile").click();
        await page.locator("#profile-active-group").selectOption(String(f.otherGroup));
        await page.locator("#save-active-group").click();
        await page.waitForFunction(({group, team}) => currentUser.active_group_id === group
            && document.querySelector('#global-team-filter option[value="' + team + '"]'), {group: f.otherGroup, team: f.foreignTeam});
        await page.goBack();
        await dashboardRows([f.foreign]);
        assert.deepEqual(await page.evaluate(() => getTableFilterValues("#dashboard-service-filter")), []);
        assert.deepEqual(await page.evaluate(() => Object.keys(document.querySelector("#dashboard-service-filter").tomselect.options)), [String(f.foreignService)]);

        await page.setViewportSize({width: 390, height: 844});
        await openFilters();
        await page.locator("#dashboard-my-alerts").click();
        await dashboardRows([f.foreign]);
        await setService(f.foreignService);
        await dashboardRows([f.foreign]);
        await page.locator("#dashboard-toggle-filters").scrollIntoViewIfNeeded();
        await page.screenshot({path: path.join(f.screenshots, "mobile.png")});
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), "page must not overflow horizontally");
        await page.locator("#dashboard-toggle-filters").click();
        assert.equal(await page.locator("#dashboard-alert-filters").isVisible(), false);
        assert.deepEqual(errors, []);
    } catch (error) {
        console.error(await page.evaluate(() => ({url: location.href,
            filters: location.search, rows: document.querySelector("#alerts-table").textContent,
            pickerClass: document.querySelector("#dashboard-involvement-filter").tomselect.wrapper.className,
            shared: AlertFilterState.saved("dashboard").toString()})));
        throw error;
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
