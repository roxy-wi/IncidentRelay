"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.STANDARD_EDITOR_FIXTURE);

async function main() {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const context = await browser.newContext({baseURL: fixture.baseUrl,
        viewport: {width: 1440, height: 1000}, serviceWorkers: "block"});
    await context.addCookies([
        {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
        {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
    ]);
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
        ? route.continue() : route.abort());
    const standardUrl = `/api/services/standards/${fixture.standardId}`;
    const checkUrl = `${standardUrl}/checks/${fixture.checkId}`;
    const standardModal = page.locator("#service-standard-modal");
    const checkModal = page.locator("#service-standard-check-modal");
    let writes = 0;
    page.on("request", request => {
        if (["PUT", "POST"].includes(request.method()) && new URL(request.url()).pathname.startsWith("/api/services/standards")) writes++;
    });
    async function waitForApiIdle() {
        // Saving triggers follow-up AJAX refreshes after the document has loaded.
        await page.waitForFunction(() => window.jQuery && window.jQuery.active === 0);
    }
    async function openStandard() {
        await waitForApiIdle();
        const row = page.locator("#service-standards-list tr").filter({hasText: "Production readiness"});
        await row.locator(".app-action-menu-toggle").click();
        await page.locator(".app-action-menu-portal.is-open").getByRole("menuitem", {name: /^(Edit|Изменить)$/}).click();
        await standardModal.waitFor({state: "visible"});
    }
    async function openCheck() {
        await waitForApiIdle();
        await page.locator("#service-standards-list .name-button").filter({hasText: "Production readiness"}).click();
        await waitForApiIdle();
        const row = page.locator("#service-standard-checks-list tr").filter({hasText: "Service description"});
        await row.locator(".app-action-menu-toggle").click();
        await page.locator(".app-action-menu-portal.is-open").getByRole("menuitem", {name: /^(Edit|Изменить)$/}).click();
        await checkModal.waitFor({state: "visible"});
    }
    async function save(selector, url, modal, method = "PUT") {
        const response = page.waitForResponse(r => new URL(r.url()).pathname === url && r.request().method() === method);
        await page.locator(selector).click();
        const result = await response;
        assert.equal(result.status(), method === "POST" ? 201 : 200, await result.text());
        await modal.waitFor({state: "hidden"});
        await waitForApiIdle();
        return result.json();
    }
    async function screenshot(name) {
        fs.mkdirSync(fixture.screenshotDir, {recursive: true});
        await page.screenshot({path: path.join(fixture.screenshotDir, name), animations: "disabled"});
    }
    async function layout(modal) {
        assert(await modal.evaluate(element => {
            const body = element.querySelector(".app-modal-body");
            const dialog = element.querySelector(".app-modal-dialog").getBoundingClientRect();
            const footer = element.querySelector(".app-modal-footer").getBoundingClientRect();
            return body.scrollWidth <= body.clientWidth + 1 && dialog.left >= 0 &&
                dialog.right <= innerWidth && footer.bottom <= innerHeight && footer.top > 0;
        }), "Editor should fit the viewport with accessible actions");
    }
    try {
        await page.goto("/services");
        await page.locator('[data-services-tab="standards"]').click();
        await waitForApiIdle();
        await page.evaluate(async () => {
            document.querySelector("#service-standards-list .app-action-menu-toggle").click();
            window.closeOpenedActionMenu();
            await new Promise(resolve => requestAnimationFrame(resolve));
        });
        assert.equal(await page.locator(".app-action-menu-list:visible").count(), 0,
            "A queued positioning frame must not reopen a closed menu");
        await page.locator("#service-standards-list tr").filter({hasText: "Production readiness"})
            .locator(".app-action-menu-toggle").click();
        await page.evaluate(() => loadServiceStandards());
        await waitForApiIdle();
        assert.equal(await page.locator(".app-action-menu-portal").count(), 0,
            "Refreshing standards must clean up an open action menu");
        await openStandard();
        assert.equal(await standardModal.locator(".ts-wrapper").count(), 6);
        assert.deepEqual(await page.locator("#service-standard-kind").evaluate(e => Array.from(e.selectedOptions, o => o.value)), ["technical", "component"]);
        await layout(standardModal);
        await screenshot("standard-editor-desktop.png");

        // Saving a description preserves all selectors, including API-configured labels/components.
        await page.locator("#service-standard-description").fill("Updated operational requirements");
        const saved = await save("#save-service-standard", standardUrl, standardModal);
        assert.deepEqual(saved.applies_to, fixture.scope);
        await openStandard();
        const environment = page.locator("#service-standard-environment").locator("..");
        await environment.locator('.item[data-value="staging"] .remove').click();
        await environment.locator(".ts-control input").fill("Testing");
        await environment.locator('.ts-dropdown [data-value="testing"]').click();
        await page.locator("#service-standard-name").click();
        const expectedScope = {...fixture.scope, environments: ["production", "testing"]};

        // Failed saves keep the draft; retry and repeated clicks do not duplicate writes.
        await page.route(`**${standardUrl}`, route => route.fulfill({status: 503,
            contentType: "application/json", body: '{"message":"Temporary test failure"}'}), {times: 1});
        await page.locator("#save-service-standard").click();
        await standardModal.locator(".standard-editor-error").waitFor({state: "visible"});
        assert.equal(await page.locator("#service-standard-description").inputValue(), "Updated operational requirements");
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        await page.route(`**${standardUrl}`, async route => { await gate; await route.continue(); }, {times: 1});
        const before = writes;
        const response = page.waitForResponse(r => new URL(r.url()).pathname === standardUrl && r.request().method() === "PUT");
        await page.locator("#save-service-standard").evaluate(button => { button.click(); button.click(); });
        assert(await page.locator("#save-service-standard").isDisabled());
        await page.locator("#service-standard-name").press("Escape");
        assert(await standardModal.isVisible());
        release();
        assert.deepEqual((await (await response).json()).applies_to, expectedScope);
        await standardModal.waitFor({state: "hidden"});
        assert.equal(writes, before + 1);

        await openCheck();
        await layout(checkModal);
        await screenshot("standard-check-desktop.png");
        const field = page.locator("#service-standard-check-field");
        const valueType = page.locator("#service-standard-check-value-type");
        const value = page.locator("#service-standard-check-value");
        const type = page.locator("#service-standard-check-type");
        const config = page.locator("#service-standard-check-configuration");
        assert.equal(await field.inputValue(), "description");
        assert.equal(await config.count(), 0, "Field checks should not require configuration JSON");
        assert.equal(await value.count(), 0, "Presence checks only need a field");
        const beforeInvalid = writes;
        await field.selectOption("");
        await page.locator("#save-service-standard-check").click();
        assert(await page.locator("#standard-check-field-error").isVisible());
        assert.equal(writes, beforeInvalid);
        await field.selectOption("description");
        const presentCheck = await save("#save-service-standard-check", checkUrl, checkModal);
        assert.deepEqual(presentCheck.configuration, {field: "description"});
        await openCheck();
        await type.selectOption("field_equals");
        assert.equal(await field.inputValue(), "description");
        await field.selectOption("environment");
        assert.equal(await valueType.inputValue(), "string");
        assert.equal(await value.getAttribute("list"), "standard-check-value-options");
        await value.fill("production");

        // Switching check types preserves each draft, even invalid JSON in another type.
        await type.selectOption("metadata_value");
        const beforeInvalidJson = writes;
        for (const invalid of ["", "{", "[]", "null", "true"]) {
            await config.fill(invalid);
            await page.locator("#save-service-standard-check").click();
            assert(await page.locator("#standard-check-config-error").isVisible());
            assert.equal(await config.getAttribute("aria-invalid"), "true");
        }
        assert.equal(writes, beforeInvalidJson);
        await type.selectOption("field_equals");
        assert.equal(await value.inputValue(), "production");
        await type.selectOption("field_present");
        assert.equal(await field.inputValue(), "description");
        assert.equal(await value.count(), 0);
        await type.selectOption("metadata_value");
        assert.equal(await config.inputValue(), "true");
        await config.fill('{"key":"pci","value":true}');
        await page.locator("#format-standard-check-json").click();
        assert.equal(await config.inputValue(), JSON.stringify({key: "pci", value: true}, null, 2));
        await type.selectOption("field_equals");
        const configuration = {field: "environment", value: "production"};
        await screenshot("standard-check-fields-desktop.png");
        await page.locator("#service-standard-check-weight").fill("0");
        await page.locator("#save-service-standard-check").click();
        assert.equal(writes, beforeInvalidJson);
        await page.locator("#service-standard-check-weight").fill("25");
        await page.locator("#service-standard-check-position").fill("20000");
        const updatedCheck = await save("#save-service-standard-check", checkUrl, checkModal);
        assert.deepEqual(updatedCheck.configuration, configuration);
        assert.equal(updatedCheck.weight, 25);
        assert.equal(updatedCheck.position, 20000);
        assert.equal(updatedCheck.required, true);

        // Values retain their exact JSON types through save/reopen, including false, 0 and null.
        const cases = [
            ["public_order", "number", 0],
            ["enabled", "boolean", false],
            ["enabled", "string", "false"],
            ["description", "string", "  {\"text\":\"quoted\"}  "],
            ["description", "string", ""],
            ["description", "null", null],
            ["metadata", "json", {pci: true, regions: ["eu", "us"]}],
            ["tags", "json", ["critical", "payments"]],
        ];
        for (const [name, kind, expected] of cases) {
            await openCheck();
            await field.selectOption(name);
            await valueType.selectOption(kind);
            if (kind === "number" || kind === "json") {
                await value.fill(kind === "json" ? "{" : "");
                const beforeBadValue = writes;
                await page.locator("#save-service-standard-check").click();
                assert.equal(writes, beforeBadValue);
                assert(await page.locator("#standard-check-field-error").isVisible());
            }
            if (kind === "boolean") await value.selectOption(String(expected));
            else if (kind !== "null") await value.fill(kind === "json" ? JSON.stringify(expected) : String(expected));
            const result = await save("#save-service-standard-check", checkUrl, checkModal);
            assert.deepEqual(result.configuration, {field: name, value: expected});
            await openCheck();
            assert.equal(await field.inputValue(), name);
            assert.equal(await valueType.inputValue(), kind);
            if (kind === "null") assert.equal(await value.count(), 0);
            else assert.equal(await value.inputValue(), kind === "json" ? JSON.stringify(expected, null, 2) : String(expected));
            await checkModal.locator("[data-editor-cancel]").click();
        }

        // A legacy relation attribute not in the suggested list stays intact.
        const legacy = {...updatedCheck, configuration: {field: "team", value: fixture.teamId}};
        const legacyPayload = Object.fromEntries(["name", "slug", "description", "check_type", "configuration",
            "weight", "position", "severity", "required", "enabled"].map(key => [key, legacy[key]]));
        assert.equal((await page.request.put(checkUrl, {data: legacyPayload})).status(), 200);
        await openCheck();
        assert.equal(await field.inputValue(), "team");
        assert.equal(await valueType.inputValue(), "number");
        const kept = await save("#save-service-standard-check", checkUrl, checkModal);
        assert.deepEqual(kept.configuration, legacyPayload.configuration);

        await openCheck();
        await field.selectOption("environment");
        await value.fill("production");
        await page.route(`**${checkUrl}`, route => route.fulfill({status: 503,
            contentType: "application/json", body: '{"message":"Temporary test failure"}'}), {times: 1});
        await page.locator("#save-service-standard-check").click();
        await checkModal.locator(".standard-editor-error").waitFor({state: "visible"});
        assert.equal(await value.inputValue(), "production");
        assert.deepEqual((await save("#save-service-standard-check", checkUrl, checkModal)).configuration, configuration);

        await openStandard();
        await page.locator("#service-standard-name").fill("Cancelled change");
        await standardModal.locator("[data-editor-cancel]").click();
        await openStandard();
        assert.equal(await page.locator("#service-standard-name").inputValue(), "Production readiness");
        await standardModal.locator("[data-editor-cancel]").click();

        await page.locator("#new-service-standard-btn").click();
        await page.locator("#service-standard-name").fill("All services standard");
        assert.equal(await page.locator("#service-standard-slug").inputValue(), "all-services-standard");
        for (const id of ["kind", "lifecycle"]) {
            await page.locator(`#service-standard-${id}`).locator("..").locator(".remove").click();
        }
        const created = await save("#save-service-standard", "/api/services/standards", standardModal, "POST");
        assert.deepEqual(created.applies_to, {});
        await page.locator("#new-service-standard-check-btn").click();
        await page.locator("#service-standard-check-name").fill("Description configured");
        assert.equal(await page.locator("#service-standard-check-slug").inputValue(), "description-configured");
        await type.selectOption("field_present");
        await field.selectOption("description");
        const newCheck = await save("#save-service-standard-check", `/api/services/standards/${created.id}/checks`, checkModal, "POST");
        assert.deepEqual(newCheck.configuration, {field: "description"});

        await context.addCookies([{name: "incidentrelay_locale", value: "ru", url: fixture.baseUrl}]);
        await page.reload();
        await page.locator('[data-services-tab="standards"]').click();
        await openStandard();
        assert.match(await page.locator("#standard-scope-heading").innerText(), /Область применения/);
        await page.emulateMedia({colorScheme: "dark"});
        await page.waitForFunction(() => document.documentElement.dataset.colorScheme === "dark");
        await screenshot("standard-editor-dark-ru.png");
        await standardModal.locator("[data-editor-cancel]").click();
        await openCheck();
        await screenshot("standard-check-dark-ru.png");
        for (const width of [768, 390, 320]) {
            await page.setViewportSize({width, height: 844});
            await layout(checkModal);
            if (width === 390) {
                await checkModal.locator(".app-modal-body").evaluate(element => { element.scrollTop = element.scrollHeight; });
                await screenshot("standard-check-fields-mobile-ru.png");
            }
        }
        await checkModal.locator("[data-editor-cancel]").click();
        await page.emulateMedia({colorScheme: "light"});
        await page.setViewportSize({width: 390, height: 844});
        await openStandard();
        await standardModal.locator(".app-modal-body").evaluate(element => { element.scrollTop = element.scrollHeight; });
        await layout(standardModal);
        await screenshot("standard-editor-mobile-ru.png");
        assert.deepEqual(errors, []);
    } catch (error) {
        await screenshot("standard-editor-failure.png");
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
