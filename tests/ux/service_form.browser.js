"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.SERVICE_FORM_FIXTURE);

async function main() {
    const browser = await chromium.launch({
        headless: true,
        channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    });
    const context = await browser.newContext({
        baseURL: fixture.baseUrl, viewport: {width: 1440, height: 1080}, serviceWorkers: "block",
    });
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
    const endpoint = `/api/services/${fixture.serviceId}`;
    let writes = 0;
    page.on("request", request => {
        if (request.method() === "PUT" && new URL(request.url()).pathname === endpoint) writes++;
    });
    const editor = page.locator("#service-metadata");
    const modal = page.locator("#service-form-modal");
    async function openEdit() {
        await page.waitForFunction(id => typeof getServiceById === "function" && getServiceById(id), fixture.serviceId);
        const row = page.locator("#services-table tr").filter({hasText: "Payments API"});
        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: /^(Edit|Изменить|Редактировать)$/}).click();
        await modal.waitFor({state: "visible"});
    }
    async function save() {
        const response = page.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.request().method() === "PUT");
        await page.locator("#save-service").click();
        assert.equal((await response).status(), 200);
        await modal.waitFor({state: "hidden"});
        const saved = await (await context.request.get(endpoint)).json();
        await page.waitForFunction(({id, metadata}) =>
            JSON.stringify(getServiceById(id).metadata) === JSON.stringify(metadata),
        {id: fixture.serviceId, metadata: saved.metadata});
        return saved;
    }
    async function screenshot(name) {
        fs.mkdirSync(fixture.screenshotDir, {recursive: true});
        await page.screenshot({path: path.join(fixture.screenshotDir, name), animations: "disabled"});
    }
    async function assertLayout() {
        assert(await modal.evaluate(element => {
            const body = element.querySelector(".app-modal-body");
            const footer = element.querySelector(".app-modal-footer").getBoundingClientRect();
            const dialog = element.querySelector(".app-modal-dialog").getBoundingClientRect();
            return body.scrollWidth <= body.clientWidth + 1 && dialog.left >= 0 &&
                dialog.right <= innerWidth && footer.bottom <= innerHeight && footer.top > 0;
        }), "Form must fit the viewport with a visible footer and no horizontal overflow");
    }
    async function checkServiceWorkspaces() {
        await context.addCookies([{name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
        await page.setViewportSize({width: 1440, height: 1080});
        await page.goto("/services");
        await page.waitForFunction(id => typeof getServiceById === "function" && getServiceById(id), fixture.serviceId);
        await page.evaluate(id => openServiceDetailsModal(id), fixture.serviceId);
        await page.locator("#service-details-modal .workspace-section[data-section=history]").waitFor();
        const reference = {};
        for (const [selector, kind] of [
            ["#service-details-modal", "service"],
            ["#business-service-details-modal", "business"],
        ]) {
            if (kind === "business") {
                await page.locator("#close-service-details-modal").click();
                await page.goto("/business-services");
                await page.waitForFunction(() => typeof openBusinessServiceDetailsModal === "function" &&
                    document.querySelector("#business-services-table .app-action-menu-toggle"));
                await page.evaluate(id => openBusinessServiceDetailsModal(id), fixture.businessServiceId);
            }
            const details = page.locator(selector);
            await details.waitFor({state: "visible"});
            for (const theme of ["light", "dark"]) {
                await page.evaluate(value => window.AppTheme.apply(value), theme);
                const appearance = await details.evaluate(element => {
                    const sections = Array.from(element.querySelectorAll(".workspace-section"));
                    return sections.map(section => {
                        const header = section.querySelector(":scope > .card-header");
                        const heading = header.querySelector(".section-heading");
                        const icon = heading.querySelector(".section-icon");
                        const style = getComputedStyle(section);
                        return {category: section.dataset.section, icon: icon.querySelector("i").className,
                            color: getComputedStyle(icon).color, border: style.borderTopColor,
                            titleSize: getComputedStyle(heading.querySelector("h3")).fontSize,
                            subtitleInside: !section.querySelector(":scope > .card-subtitle")};
                    });
                });
                assert(appearance.length >= (kind === "service" ? 13 : 4));
                for (const item of appearance) {
                    assert.equal(item.titleSize, "16px");
                    assert(item.subtitleInside);
                    const key = theme + ":" + item.category;
                    if (reference[key]) assert.deepEqual(item, reference[key], "Same category must share appearance: " + key);
                    else reference[key] = item;
                }
                await details.locator(".app-modal-body").evaluate(element => element.scrollTop = 0);
                await screenshot(`${kind}-details-${theme}.png`);
            }
            for (const width of [768, 390, 320]) {
                await page.setViewportSize({width, height: 844});
                assert(await details.evaluate(element => {
                    const dialog = element.querySelector(".app-modal-dialog").getBoundingClientRect();
                    const body = element.querySelector(".app-modal-body");
                    return dialog.left >= 0 && dialog.right <= innerWidth + 1 &&
                        body.scrollWidth <= body.clientWidth + 1;
                }), `${kind} details must fit ${width}px; tables scroll within their sections`);
                if (width === 390) await screenshot(`${kind}-details-mobile.png`);
            }
            await page.setViewportSize({width: 1440, height: 1080});
        }
        // Existing nested actions still open the component editor and save changes.
        await page.locator("#open-business-service-component-modal").click();
        await page.locator("#business-service-component-modal").waitFor({state: "visible"});
        await page.locator("#close-business-service-component-modal").click();
        await page.locator("#business-service-manual-status").selectOption("degraded");
        await page.locator("#business-service-manual-status-message").fill("Layout regression check");
        const saved = page.waitForResponse(response => response.url().includes("/manual-status") && response.request().method() === "POST");
        await page.locator("#set-business-service-manual-status").click();
        assert.equal((await saved).status(), 200);
        await page.locator("#close-business-service-details-modal").click();
    }
    try {
        await page.goto("/services");
        // Shared helpers must retain their legacy behavior for other pages.
        assert.deepEqual(await page.evaluate(() => {
            const field = $("<textarea>").appendTo("body");
            const button = $("<button>").html("<span>Save</span>");
            const originallyDisabled = $("<button>").prop("disabled", true);
            const probe = $("<div>").addClass("app-modal").hide().append(
                $("<div>").addClass("app-modal-footer").append(button, originallyDisabled)
            ).appendTo("body");
            const originalShowError = window.showAppError;
            const messages = [];
            window.showAppError = message => messages.push(message);
            try {
                const results = [];
                field.val("");
                results.push(parseJsonInput(field, "fallback") === "fallback");
                field.val("  ");
                results.push(formatJsonTextarea(field, {}, "Config") && field.val() === "{}");
                for (const value of [null, false, 0, ["a"], {nested: [false, 0]}]) {
                    field.val(JSON.stringify(value));
                    results.push(JSON.stringify(parseJsonInput(field)) === JSON.stringify(value));
                    results.push(formatJsonTextarea(field, {}, "Config") && field.val() === JSON.stringify(value, null, 2));
                }
                field.val("{");
                results.push(formatJsonTextarea(field, {}, "Config") === false && field.val() === "{");
                try { parseJsonInput(field); results.push(false); }
                catch (error) { results.push(error instanceof SyntaxError); }
                results.push(messages.length === 2);

                AppLoading.setButtonLoading(button, true);
                results.push(button.prop("disabled") && button.find(".ui-loading-spinner").length === 1);
                AppLoading.setButtonLoading(button, true);
                AppLoading.setButtonLoading(button, false);
                results.push(!button.prop("disabled") && button.html() === "<span>Save</span>");
                probe.addClass("is-open");
                setAppModalSaving(probe, true);
                setAppModalSaving(probe, true);
                closeAppModal(probe);
                results.push(probe.hasClass("is-open") && button.prop("disabled") && button.html() === "<span>Save</span>");
                setAppModalSaving(probe, false);
                results.push(!button.prop("disabled") && originallyDisabled.prop("disabled"));
                closeAppModal(probe);
                results.push(probe.hasClass("is-hidden"));
                return results.every(Boolean);
            } finally {
                window.showAppError = originalShowError;
                field.remove();
                probe.remove();
            }
        }), true);
        await openEdit();
        assert.deepEqual(JSON.parse(await editor.inputValue()), fixture.metadata);
        assert.match(await page.locator("#service-metadata-hint").innerText(), /platform-team/);
        await assertLayout();
        await screenshot("service-form-desktop.png");

        // Editing an ordinary field must preserve all existing metadata and hidden fields.
        await page.locator("#service-description").fill("Updated description");
        const saved = await save();
        assert.deepEqual(saved.metadata, fixture.metadata);
        assert.deepEqual(saved.labels, {cost_center: "payments"});
        assert.deepEqual(saved.tags, ["customer-facing", "pci"]);
        assert.equal(saved.lifecycle, "development");
        assert.equal(saved.public_name, "Payments");
        assert.equal(saved.public_description, "Payment processing");
        assert.equal(saved.public_order, 0);

        await openEdit();
        const exclusions = page.locator("#service-change-exclusions");
        assert.equal(await page.locator("#service-change-correlation-enabled").isChecked(), false);
        assert.equal(await exclusions.inputValue(), "[]");
        const beforeInvalidRules = writes;
        for (const invalid of ["{", "{}", "null"]) {
            await exclusions.fill(invalid);
            await page.locator("#save-service").click();
            assert(await page.locator("#service-change-exclusions-error").isVisible());
        }
        assert.equal(writes, beforeInvalidRules);
        const rules = [{source: "heartbeat"}, {labels: {kind: "synthetic"}}];
        await exclusions.fill(JSON.stringify(rules));
        await page.locator("#service-change-correlation-enabled").check();
        const policySaved = await save();
        assert.equal(policySaved.change_correlation_enabled, true);
        assert.deepEqual(policySaved.change_correlation_exclusions, rules);
        await openEdit();
        assert.equal(await page.locator("#service-change-correlation-enabled").isChecked(), true);
        assert.deepEqual(JSON.parse(await exclusions.inputValue()), rules);
        const writesBeforeInvalid = writes;
        for (const invalid of ["", "{", "[]", "null", "true", "42", '"owner"']) {
            await editor.fill(invalid);
            await page.locator("#save-service").click();
            assert(await page.locator("#service-metadata-error").isVisible());
            assert.equal(await editor.getAttribute("aria-invalid"), "true");
            assert.equal(await editor.inputValue(), invalid);
        }
        assert.equal(writes, writesBeforeInvalid, "Invalid JSON must never reach the API");

        const updated = {...fixture.metadata, owner: "Команда платформы", extra: [0, false, null, {nested: "value"}],
            text: "<script>window.metadataExecuted = true</script>"};
        await editor.fill(JSON.stringify(updated));
        await page.locator("#format-service-metadata").click();
        assert.equal(await editor.inputValue(), JSON.stringify(updated, null, 2));
        assert.equal(await page.locator("#service-metadata-error").isVisible(), false);

        // A rejected save leaves the draft intact and can be retried.
        await page.route(`**${endpoint}`, route => route.request().method() === "PUT"
            ? route.fulfill({status: 503, contentType: "application/json", body: JSON.stringify({message: "Test save failure"})})
            : route.fallback(), {times: 1});
        await page.locator("#save-service").click();
        await page.locator("#app-dialog-modal").waitFor({state: "visible"});
        assert.equal(await editor.inputValue(), JSON.stringify(updated, null, 2));
        assert.equal(await page.locator("#save-service").isDisabled(), false);
        await page.locator("#app-dialog-confirm").click();
        assert.deepEqual((await save()).metadata, updated);
        assert.equal(await page.evaluate(() => window.metadataExecuted), undefined);

        // Duplicate submits while a request is pending must result in a single write.
        await openEdit();
        await editor.fill("{}");
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        await page.route(`**${endpoint}`, async route => {
            await gate;
            await route.continue();
        }, {times: 1});
        const response = page.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.request().method() === "PUT");
        const beforeDuplicate = writes;
        await page.evaluate(() => { saveService(); saveService(); });
        assert.equal(await page.locator("#save-service").isDisabled(), true);
        await editor.press("Escape");
        assert(await modal.isVisible(), "Saving must prevent Escape from closing the form");
        await modal.click({position: {x: 2, y: 2}});
        assert(await modal.isVisible(), "Saving must prevent backdrop dismissal");
        release();
        assert.equal((await response).status(), 200);
        await modal.waitFor({state: "hidden"});
        assert.equal(writes, beforeDuplicate + 1);
        assert.deepEqual((await (await context.request.get(endpoint)).json()).metadata, {});

        // Cancellation does not save, and creating another service starts with empty metadata.
        await openEdit();
        await editor.fill('{"unsaved": true}');
        const beforeCancel = writes;
        await page.locator("#cancel-service-form").click();
        assert.equal(writes, beforeCancel);
        await page.locator("#open-service-create-modal").click();
        await modal.waitFor({state: "visible"});
        assert.equal(await editor.inputValue(), "{}");
        assert.equal(await page.locator("#service-change-correlation-enabled").isChecked(), false);
        assert.equal(await exclusions.inputValue(), "[]");
        assert.equal(await page.locator("#service-id").inputValue(), "");
        await page.locator("#service-team").selectOption(String(fixture.teamId));
        await page.locator("#service-name").fill("New service with metadata");
        await page.locator("#service-slug").fill("new-service-metadata");
        await editor.fill('{"owner": "new-team", "enabled": false}');
        const createdResponse = page.waitForResponse(r => new URL(r.url()).pathname === "/api/services" && r.request().method() === "POST");
        await page.locator("#save-service").click();
        const created = await createdResponse;
        assert.equal(created.status(), 201);
        assert.deepEqual((await created.json()).metadata, {owner: "new-team", enabled: false});
        await modal.waitFor({state: "hidden"});

        // Russian copy, dark theme and narrow screens use the same production form.
        await context.addCookies([{name: "incidentrelay_locale", value: "ru", url: fixture.baseUrl}]);
        await page.reload();
        await openEdit();
        assert.match(await page.locator("#service-metadata-heading").innerText(), /Метаданные/);
        await editor.fill(JSON.stringify(fixture.metadata, null, 2));
        await page.emulateMedia({colorScheme: "dark"});
        await page.waitForFunction(() => document.documentElement.dataset.colorScheme === "dark");
        await assertLayout();
        await screenshot("service-form-dark-ru.png");
        await page.emulateMedia({colorScheme: "light"});
        await page.waitForFunction(() => document.documentElement.dataset.colorScheme === "light");
        for (const width of [768, 390, 320]) {
            await page.setViewportSize({width, height: 844});
            await editor.scrollIntoViewIfNeeded();
            await assertLayout();
            if (width === 390) await screenshot("service-form-mobile-ru.png");
        }
        await page.locator("#cancel-service-form").click();
        await checkServiceWorkspaces();
        assert.deepEqual(errors, []);
    } catch (error) {
        await screenshot("service-form-failure.png");
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
