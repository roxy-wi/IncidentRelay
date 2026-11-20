"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.SEARCHABLE_SELECTS_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        const context = await browser.newContext({viewport: {width: 1440, height: 1050}, serviceWorkers: "block"});
        await context.addCookies([
            {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
        ]);
        await context.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        const page = await context.newPage();
        page.setDefaultTimeout(15000);
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));

        async function searchSelect(selector, search, value) {
            const select = page.locator(selector);
            const inputId = await select.evaluate(element => element.tomselect.control_input.id);
            const input = page.locator("#" + inputId);
            await input.fill(search);
            await page.waitForFunction(({selector, value}) =>
                document.querySelector(selector).tomselect.activeOption?.dataset.value === String(value), {selector, value});
            await input.press("Enter");
            assert.equal(await select.inputValue(), String(value));
        }

        await page.goto(fixture.baseUrl + "/teams");
        await page.waitForFunction(() => document.querySelector("#global-team-filter").tomselect);
        assert.ok(await page.locator("#global-team-filter option").count() > 300);
        await searchSelect("#global-team-filter", "ZZZ Search target", fixture.teamId);
        await page.waitForFunction(id => new URLSearchParams(location.search).get("team") === String(id), fixture.teamId);
        await page.reload();
        await page.waitForFunction(id => document.querySelector("#global-team-filter").tomselect?.getValue() === String(id), fixture.teamId);
        await page.evaluate(() => setSelectedTeamId("", true));
        assert.equal(await page.locator("#global-team-filter").evaluate(el => el.tomselect.getValue()), "");
        await searchSelect("#global-team-filter", "All teams", "");

        const [catalogResponse] = await Promise.all([
            page.waitForResponse(response => new URL(response.url()).pathname === "/api/event-orchestrations/catalog",
                {timeout: 60000}),
            page.goto(fixture.baseUrl + "/event-orchestration"),
        ]);
        assert.equal(catalogResponse.status(), 200, "orchestration catalog must load after the large team selector");
        await page.waitForFunction(() => orchestrationCatalogCache !== null);
        await page.locator("#create-orchestration").click();
        await page.locator("#orchestration-create-scope").selectOption("service");
        await searchSelect("#orchestration-create-service", "Search target", fixture.serviceId);
        await page.locator('#orchestration-create-modal [data-close-modal]').first().click();
        await page.locator("#create-orchestration").click();
        await page.locator("#orchestration-create-scope").selectOption("service");
        const serviceInputId = await page.locator("#orchestration-create-service").evaluate(el => el.tomselect.control_input.id);
        await page.locator(`label[for="${serviceInputId}"]`).click();
        assert.equal(await page.locator("#" + serviceInputId).evaluate(el => el === document.activeElement), true);
        await page.locator("#" + serviceInputId).fill("no matching service xyz");
        assert.equal(await page.locator("#orchestration-create-service-ts-dropdown .no-results").innerText(), "No results found");
        await page.locator("#" + serviceInputId).press("Escape");
        await page.locator('#orchestration-create-modal [data-close-modal]').first().click();

        await page.evaluate(id => openOrchestration(id), fixture.orchestrationId);
        await page.locator("#orchestration-add-rule").click();
        await page.locator("#orchestration-rule-name").fill("Searchable destinations");
        await page.locator("#orchestration-action-add").click();
        const row = index => `.orchestration-action-row[data-action-index="${index}"]`;
        await searchSelect(row(0) + " select.orchestration-action-type", "set_team", "set_team");
        await searchSelect(row(0) + " select.orchestration-action-reference", "ZZZ Search target", fixture.teamId);
        // Adding/rebuilding rows must preserve the unsaved selected destination.
        await page.locator("#orchestration-action-add").click();
        assert.equal(await page.locator(row(0) + " select.orchestration-action-reference").inputValue(), String(fixture.teamId));
        await searchSelect(row(1) + " select.orchestration-action-type", "set_service", "set_service");
        await searchSelect(row(1) + " select.orchestration-action-reference", "Search target", fixture.serviceId);
        assert.equal(await page.locator("#orchestration-action-editor .searchable-select").count(), 4);
        assert.equal(await page.locator("#orchestration-action-editor .ts-control team, #orchestration-action-editor .ts-control service").count(), 0);
        await page.screenshot({path: path.join(fixture.screenshots, "orchestration.png"), fullPage: true});
        await page.locator("#orchestration-rule-save").click();
        const saved = page.waitForResponse(response => response.url().endsWith(`/api/event-orchestrations/${fixture.orchestrationId}/draft`)
            && response.request().method() === "PUT");
        await page.locator("#orchestration-save-draft").click();
        const response = await saved;
        assert.equal(response.status(), 200);
        assert.deepEqual((await response.json()).definition.rules[0].actions, [
            {type: "set_team", team_id: fixture.teamId},
            {type: "set_service", service_id: fixture.serviceId},
        ]);
        await page.locator("[data-rule-edit='0']").click();
        assert.equal(await page.locator(row(1) + " select.orchestration-action-reference").inputValue(), String(fixture.serviceId));
        await page.locator("[data-action-remove='1']").click();
        assert.equal(await page.locator("#orchestration-action-editor .searchable-select").count(), 2);
        await page.locator('#orchestration-rule-modal [data-close-modal]').first().click();

        await page.locator("#topbar-profile").click();
        await page.locator("#profile-active-group").selectOption(String(fixture.foreignGroupId));
        await page.locator("#save-active-group").click();
        await page.waitForFunction(id => document.querySelector("#global-team-filter").tomselect?.options[String(id)], fixture.foreignTeamId);
        assert.equal(await page.locator("#global-team-filter").evaluate((el, id) => !!el.tomselect.options[String(id)], fixture.teamId), false);
        await searchSelect("#global-team-filter", "Foreign team", fixture.foreignTeamId);
        assert.equal(await page.locator(".global-team-select").count(), 1);
        await page.locator(".topbar").screenshot({path: path.join(fixture.screenshots, "topbar.png")});
        await page.setViewportSize({width: 390, height: 844});
        await page.locator(".topbar").screenshot({path: path.join(fixture.screenshots, "mobile.png")});
        const bounds = await page.locator(".global-team-select").boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390, "team selector must fit the mobile viewport");
        await page.evaluate(() => document.documentElement.dataset.colorScheme = "dark");
        await page.locator(".topbar").screenshot({path: path.join(fixture.screenshots, "dark.png")});
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
