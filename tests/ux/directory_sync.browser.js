"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.DIRECTORY_SYNC_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1440, height: 1080},
        serviceWorkers: "block", locale: "en-GB", timezoneId: "Europe/Moscow"});
    await context.addCookies([{name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
        {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    async function assertLoading(button, message) {
        assert.equal(await page.locator(button + " .ui-loading-spinner").isVisible(), true);
        assert.equal(await page.locator(button).getAttribute("aria-busy"), "true");
        assert.equal(await page.locator("#ds-status .ui-loading-spinner").count(), 1);
        assert.match(await page.locator("#ds-status").textContent(), message);
        for (const id of ["sample", "preview", "apply", "run", "save"]) {
            assert.equal(await page.locator("#ds-" + id).isDisabled(), true);
        }
    }
    await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl ? route.continue() : route.abort());
    try {
        await page.goto("/admin/change-integrations");
        await page.waitForFunction(() => document.querySelector("#ci-list-status").textContent.includes("No integrations"));
        assert.ok((await page.locator("#view-change-integrations .card-header").boundingBox()).height < 80, "compact change integrations header");
        await page.screenshot({path: path.join(fixture.screenshots, "change-integrations-header.png"), fullPage: true});
        await page.goto("/admin/directory-sync");
        await page.waitForFunction(() => directorySyncOptions !== null);
        assert.ok((await page.locator("#view-directory-sync .card-header").boundingBox()).height < 80, "compact directory sync header");
        await page.screenshot({path: path.join(fixture.screenshots, "directory-sync-header.png"), fullPage: true});
        const modal = page.locator("#ds-editor");
        assert.equal(await modal.isVisible(), false);
        assert.equal(await page.locator("#ds-form").count(), 1);
        await page.locator("#ds-new").click();
        assert.equal(await page.locator("#ds-skip-tls").isChecked(), false);
        assert.equal(await modal.getAttribute("role"), "dialog");
        assert.equal(await modal.getAttribute("aria-hidden"), "false");
        assert.equal(await page.evaluate(() => document.activeElement.id), "ds-name");
        const headerBounds = await modal.locator(".app-modal-header").boundingBox();
        const legendBounds = await modal.locator("legend").first().boundingBox();
        assert.ok(legendBounds.y - headerBounds.y - headerBounds.height <= 32, "connection section follows modal header without empty space");
        assert.ok((await page.locator("#ds-headers").boundingBox()).height < 50, "authentication headers use a compact input");
        assert.equal(await page.locator("#ds-enabled").isDisabled(), true);
        assert.match(await page.locator("#ds-enabled-hint").textContent(), /Save the source/);
        assert.equal(await page.locator("#ds-enabled-label").getAttribute("title"), await page.locator("#ds-enabled-hint").textContent());
        await page.locator("#ds-headers").fill('{"Authorization":"discard-this-secret"}');
        await page.keyboard.press("Escape");
        assert.equal(await modal.isVisible(), false);
        assert.equal(await page.locator("#ds-headers").inputValue(), "");
        assert.equal(await page.evaluate(() => document.activeElement.id), "ds-new");
        await page.locator("#ds-new").click();
        await page.locator("#ds-close").focus();
        await page.keyboard.press("Shift+Tab");
        assert.equal(await page.evaluate(() => document.activeElement.id), "ds-close-footer");
        await page.keyboard.press("Tab");
        assert.equal(await page.evaluate(() => document.activeElement.id), "ds-close");
        await modal.click({position: {x: 2, y: 2}});
        assert.equal(await modal.isVisible(), false);
        await page.locator("#ds-new").click();
        await page.locator("#ds-name").fill("OnCall <test>");
        await page.locator("#ds-skip-tls").check();
        await page.locator("#ds-headers").fill('{"Authorization":"PAT browser-secret"}');
        const created = page.waitForResponse(response => response.url().endsWith("/api/admin/directory-sync") && response.request().method() === "POST");
        await page.locator("#ds-save").click();
        const response = await created;
        assert.equal(response.status(), 201, await response.text());
        const source = await response.json();
        assert.equal(source.config.verify_tls, false);
        await page.waitForFunction(() => directorySyncSource?.id);
        assert.equal(await modal.isVisible(), true);
        assert.equal(await page.locator("#ds-group").isDisabled(), true);
        assert.equal(await page.locator("#ds-headers").inputValue(), "");
        assert.equal(await page.locator("#ds-enabled").isDisabled(), true);
        assert.match(await page.locator("#ds-enabled-hint").textContent(), /Preview the changes and apply/);
        const sampleButtonBounds = await page.locator("#ds-sample").boundingBox();
        const mappingBounds = await page.locator("#ds-mapping").boundingBox();
        assert.ok(sampleButtonBounds.width < mappingBounds.width / 2, "inspect action is a compact button, not a full-width heading");
        let releaseSample;
        let sampleGate = new Promise(resolve => { releaseSample = resolve; });
        let sampleRequests = 0;
        await page.route("**/api/admin/directory-sync/*/sample", async route => {
            sampleRequests++;
            await sampleGate;
            await route.fulfill({status: 503, json: {message: "Inspection temporarily unavailable"}});
        });
        try {
            await page.locator("#ds-sample").click();
            await assertLoading("#ds-sample", /Inspecting response fields/);
            await page.locator("#ds-sample").evaluate(button => button.click());
            assert.equal(sampleRequests, 1, "inspection cannot be submitted twice");
            await page.screenshot({path: path.join(fixture.screenshots, "inspect-loading.png"), fullPage: true});
        } finally { releaseSample(); }
        await page.locator("#app-dialog-confirm").click();
        assert.match(await page.locator("#ds-status").textContent(), /Inspection temporarily unavailable/);
        assert.equal(await page.locator("#ds-status .ui-loading-spinner").count(), 0);
        assert.equal(await page.locator("#ds-sample").isEnabled(), true);
        assert.equal(await page.locator("#ds-sample").getAttribute("aria-busy"), null);
        await page.unroute("**/api/admin/directory-sync/*/sample");
        sampleGate = new Promise(resolve => { releaseSample = resolve; });
        await page.route("**/api/admin/directory-sync/*/sample", async route => {
            await sampleGate;
            await route.continue();
        });
        try {
            await page.locator("#ds-sample").click();
            await assertLoading("#ds-sample", /Inspecting response fields/);
        } finally { releaseSample(); }
        await page.locator("#ds-sample-output").waitFor({state: "visible"});
        await page.unroute("**/api/admin/directory-sync/*/sample");
        assert.equal(await page.locator("#ds-sample .ui-loading-spinner").count(), 0);
        assert.match(await page.locator("#ds-sample-output").textContent(), /enrolledScopeUuid/);
        let releasePreview;
        const previewGate = new Promise(resolve => { releasePreview = resolve; });
        await page.route("**/api/admin/directory-sync/*/preview", async route => {
            await previewGate;
            await route.continue();
        });
        try {
            await page.locator("#ds-preview").click();
            await assertLoading("#ds-preview", /Loading preview/);
            assert.equal(await page.locator("#ds-enabled").isDisabled(), true);
            assert.match(await page.locator("#ds-enabled-hint").textContent(), /Wait for the current operation/);
        } finally { releasePreview(); }
        await page.waitForFunction(() => !directorySyncSaving);
        await assertLoading("#ds-preview", /Preview queued/);
        await page.setViewportSize({width: 390, height: 844});
        await modal.locator(".app-modal-body").evaluate(element => { element.scrollTop = 0; });
        assert.ok(await modal.locator(".app-modal-body").evaluate(element => element.scrollWidth <= element.clientWidth + 2), "loading message fits the mobile modal");
        await page.screenshot({path: path.join(fixture.screenshots, "preview-queued-mobile.png"), fullPage: true});
        await page.setViewportSize({width: 1440, height: 1080});
        // Hold one status response in the running state to exercise the worker
        // phase even when the tiny fixture finishes before the first poll.
        await page.route("**/api/admin/directory-sync/" + source.id, async route => {
            const response = await route.fetch();
            await route.fulfill({response, json: {...await response.json(), pending_mode: "preview", running: true}});
        }, {times: 1});
        await page.waitForFunction(() => directorySyncSource?.running);
        await page.locator("#ds-preview").scrollIntoViewIfNeeded();
        await assertLoading("#ds-preview", /Loading preview/);
        await page.unroute("**/api/admin/directory-sync/*/preview");
        await page.locator("#ds-close-footer").click();
        assert.equal(await page.evaluate(() => directorySyncOpen), false);
        assert.equal(await page.getByRole("menuitem", {name: "Configure", exact: true}).isVisible(), false);
        await page.locator("#ds-list .app-action-menu-toggle").first().click();
        await page.getByRole("menuitem", {name: "Configure", exact: true}).click();
        await page.waitForFunction(() => directorySyncSource?.preview_token && !directorySyncSource.pending_mode);
        assert.equal(await page.locator("#ds-skip-tls").isChecked(), true);
        assert.ok(await page.locator("#ds-preview-table tr").count() >= 5);
        const previewToken = await page.evaluate(() => directorySyncSource.preview_token);
        await page.locator("#ds-name").fill("OnCall <test> reviewed");
        const savedName = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "PUT");
        await page.locator("#ds-save").click();
        const nameResponse = await savedName;
        assert.equal(nameResponse.status(), 200, await nameResponse.text());
        await page.waitForFunction(() => directorySyncSource?.name === "OnCall <test> reviewed");
        assert.equal(await page.evaluate(() => directorySyncSource.preview_token), previewToken);
        assert.equal(await page.locator("#ds-apply").isEnabled(), true);
        assert.match(await page.locator("#ds-status").textContent(), /No new preview is required/);
        await page.locator("#ds-editor .app-modal-body").evaluate(element => { element.scrollTop = 0; });
        await page.screenshot({path: path.join(fixture.screenshots, "desktop.png"), fullPage: true});
        let releaseApply;
        const applyGate = new Promise(resolve => { releaseApply = resolve; });
        await page.route("**/api/admin/directory-sync/*/apply", async route => {
            await applyGate;
            await route.continue();
        });
        try {
            await page.locator("#ds-apply").click();
            await assertLoading("#ds-apply", /Applying changes/);
        } finally { releaseApply(); }
        await page.waitForFunction(() => directorySyncSource?.approved && !directorySyncSource.pending_mode);
        await page.unroute("**/api/admin/directory-sync/*/apply");
        assert.equal(await page.locator("#ds-editor .ui-loading-spinner").count(), 0);
        assert.equal(await page.locator("#ds-enabled").isEnabled(), true);
        assert.equal(await page.locator("#ds-enabled-hint").isVisible(), false);
        assert.equal(await page.locator("#ds-enabled-label").getAttribute("title"), null);
        await page.locator("#ds-enabled").check();
        const saved = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "PUT");
        await page.locator("#ds-save").click();
        assert.equal((await saved).status(), 200);
        await page.waitForFunction(() => directorySyncSource?.enabled);
        await page.locator("#ds-list td:nth-child(6) time").waitFor({state: "attached"});
        const times = await page.locator("#ds-list time").evaluateAll(elements => elements.map(element => ({
            value: element.getAttribute("datetime"), text: element.textContent, title: element.title,
        })));
        assert.equal(times.length, 3, "last success and both scheduler deadlines are displayed");
        for (const time of times) {
            const expected = new Intl.DateTimeFormat("en-GB", {timeZone: "Europe/Moscow", year: "numeric",
                month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"}).format(new Date(time.value));
            assert.equal(time.text, expected, "UTC timestamps are displayed in the browser timezone");
            assert.match(time.title, /GMT\+3|MSK/);
        }
        await page.setViewportSize({width: 390, height: 844});
        await page.locator("#ds-editor .app-modal-body").evaluate(element => { element.scrollTop = 0; });
        await page.screenshot({path: path.join(fixture.screenshots, "mobile.png"), fullPage: true});
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), "page overflows horizontally");
        assert.ok(await modal.locator(".app-modal-body").evaluate(element => element.scrollWidth <= element.clientWidth + 2), "modal overflows horizontally");
        const saveBounds = await page.locator("#ds-save").boundingBox();
        assert.ok(saveBounds.y >= 0 && saveBounds.y + saveBounds.height <= 844, "save stays visible on mobile");
        await page.locator("#ds-close-footer").click();
        assert.equal(await modal.isVisible(), false);
        assert.equal(await page.evaluate(() => document.body.classList.contains("modal-open")), false);
        await page.setViewportSize({width: 1440, height: 1080});
        await page.screenshot({path: path.join(fixture.screenshots, "sync-schedule.png"), fullPage: true});
        await page.goto("/teams");
        const importedTeam = page.locator("#teams-table tr").filter({hasText: "Platform"});
        await importedTeam.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Members", exact: true}).click();
        const members = page.locator("#team-members-modal");
        await page.waitForFunction(() => document.querySelector("#team-members-table").textContent.includes("first"));
        assert.equal(await members.locator(".team-member-form-card").isVisible(), false);
        assert.equal(await members.locator(".actions-th").isVisible(), false);
        assert.equal(await members.locator(".app-action-menu-toggle").count(), 0);
        assert.match(await page.locator("#team-members-subtitle").textContent(), /Membership changes are not available/);
        await page.screenshot({path: path.join(fixture.screenshots, "imported-team-members.png"), fullPage: true});
        await page.locator("#close-team-members-modal-footer").click();
        const rosterUrl = "**/api/teams/*/users";
        await page.route(rosterUrl, route => route.fulfill({status: 503, json: {message: "Roster temporarily unavailable"}}));
        await importedTeam.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Members", exact: true}).click();
        await page.locator("#app-dialog-confirm").click();
        assert.match(await page.locator("#team-members-table").textContent(), /Unable to load team members/);
        await page.locator("#close-team-members-modal-footer").click();
        await page.unroute(rosterUrl);
        let releaseRoster;
        let rosterRequested;
        const rosterGate = new Promise(resolve => { releaseRoster = resolve; });
        const rosterStarted = new Promise(resolve => { rosterRequested = resolve; });
        let rosterRequests = 0;
        await page.route(rosterUrl, async route => {
            if (rosterRequests++ > 0) return route.continue();
            rosterRequested();
            await rosterGate;
            await route.fulfill({json: []});
        });
        try {
            await importedTeam.locator(".app-action-menu-toggle").click();
            await page.getByRole("menuitem", {name: "Members", exact: true}).click();
            await rosterStarted;
            await page.locator("#close-team-members-modal-footer").click();
            await importedTeam.locator(".app-action-menu-toggle").click();
            await page.getByRole("menuitem", {name: "Members", exact: true}).click();
            await page.waitForFunction(() => document.querySelector("#team-members-table").textContent.includes("first"));
        } finally { releaseRoster(); }
        await page.waitForFunction(() => jQuery.active === 0);
        assert.match(await page.locator("#team-members-table").textContent(), /first/, "an old response cannot replace the reopened roster");
        await page.unroute(rosterUrl);
        await page.goto("/rotations");
        await page.waitForFunction(() => document.querySelector("#rotations-table").textContent.includes("Slot 1"));
        assert.match(await page.locator("#rotations-table").textContent(), /Imported schedule/);
        await page.locator("#rotations-table .name-button").first().click();
        assert.match(await page.locator("#rotation-details-body").textContent(), /Read-only/);
        await page.locator("#rotation-details-modal").getByRole("button", {name: "Imported schedule", exact: true}).click();
        await page.waitForFunction(() => document.querySelector("#rotation-layer-cards form"));
        assert.equal(await page.locator("#rotation-layer-cards button[type=submit]").count(), 0);
        await page.goto("/admin/directory-sync");
        await page.locator("#ds-list .app-action-menu-toggle").first().click();
        await page.getByRole("menuitem", {name: "Configure", exact: true}).click();
        await page.waitForFunction(() => directorySyncSource && !directorySyncSource.running && !directorySyncSource.pending_mode);
        const lastSuccess = await page.evaluate(() => directorySyncSource.last_success_at);
        const queuedOperations = [];
        const recordQueuedOperation = request => {
            if (request.method() === "POST" && /\/directory-sync\/\d+\/(preview|apply|run)$/.test(request.url())) {
                queuedOperations.push(request.url());
            }
        };
        page.on("request", recordQueuedOperation);
        await page.locator("#ds-editable").check();
        await page.locator("#ds-interval").fill("7200");
        await page.locator("#ds-current-interval").fill("90");
        const savedRuntime = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "PUT");
        await page.locator("#ds-save").click();
        const runtimeResponse = await savedRuntime;
        assert.equal(runtimeResponse.status(), 200, await runtimeResponse.text());
        await page.waitForFunction(() => directorySyncSource?.config.editable && directorySyncSource.config.interval_seconds === 7200);
        assert.equal(await page.locator("#ds-enabled").isChecked(), true);
        assert.equal(await page.evaluate(() => directorySyncSource.approved), true);
        assert.equal(await page.evaluate(() => directorySyncSource.last_success_at), lastSuccess);
        assert.match(await page.locator("#ds-status").textContent(), /No new preview is required/);
        page.off("request", recordQueuedOperation);
        assert.deepEqual(queuedOperations, [], "saving runtime settings does not start a preview or import");
        await page.locator("#ds-enabled").uncheck();
        await page.locator("#ds-skip-tls").uncheck();
        await page.locator("#ds-editable").check();
        const editConfig = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "PUT");
        await page.locator("#ds-save").click();
        const editedConfig = await editConfig;
        assert.equal(editedConfig.status(), 200, await editedConfig.text());
        await page.waitForFunction(() => directorySyncSource && !directorySyncSource.enabled);
        await page.waitForFunction(() => [4, 5].every(index => document.querySelector("#ds-list tr")?.children[index].textContent === "—"));
        assert.equal(await page.evaluate(() => directorySyncSource.config.verify_tls), true);
        assert.equal(await page.evaluate(() => directorySyncSource.approved), true);
        assert.equal(await page.locator("#ds-enabled").isDisabled(), false);
        assert.equal(await page.locator("#ds-enabled-hint").isVisible(), false);
        await page.goto("/teams");
        await page.locator("#teams-table tr").filter({hasText: "Platform"}).locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Members", exact: true}).click();
        await page.waitForFunction(() => document.querySelector("#team-members-table").textContent.includes("first"));
        assert.equal(await members.locator(".team-member-form-card").isVisible(), true);
        assert.equal(await members.locator(".actions-th").isVisible(), true);
        assert.ok(await members.locator(".app-action-menu-toggle").count() > 0);
        await page.goto("/rotations");
        await page.locator("#rotations-table .name-button").first().click();
        await page.locator("#rotation-details-modal").getByRole("button", {name: "Imported schedule", exact: true}).click();
        const form = page.locator("#rotation-layer-cards form").first();
        await form.locator("input[maxlength='255']").fill("Locally edited shift");
        assert.ok(await form.evaluate(element => element.checkValidity()), "imported timestamps must be valid form values");
        const editShift = page.waitForResponse(r => r.url().includes("/api/rotations/imported-shifts/") && r.request().method() === "PUT");
        await form.locator("button[type=submit]").click();
        assert.equal((await editShift).status(), 200);
        await page.waitForFunction(() => document.querySelector("#rotation-layer-cards input[maxlength='255']")?.value === "Locally edited shift");
        await page.locator("#add-layer-card").click();
        const added = page.locator("#rotation-layer-cards form").first();
        const from = new Date(Date.now() + 86400000).toISOString().slice(0, 19);
        const until = new Date(Date.now() + 93600000).toISOString().slice(0, 19);
        await added.locator("input[maxlength='255']").fill("New local shift");
        await added.locator("input[type=datetime-local]").nth(0).fill(from);
        await added.locator("input[type=datetime-local]").nth(1).fill(until);
        await added.getByRole("button", {name: "Add replacement", exact: true}).click();
        const replacement = added.locator("[data-import-replacement]");
        await replacement.locator("input[type=datetime-local]").nth(0).fill(from);
        await replacement.locator("input[type=datetime-local]").nth(1).fill(until);
        await replacement.locator("input[inputmode=numeric]").fill("9223372036854775806");
        const addedResponse = page.waitForResponse(r => r.url().endsWith("/imported-shifts") && r.request().method() === "POST");
        await added.locator("button[type=submit]").click();
        const createdShift = await addedResponse;
        assert.equal(createdShift.status(), 201, await createdShift.text());
        assert.equal((await createdShift.json()).replacements[0].precedence, "9223372036854775806");
        await page.waitForFunction(() => document.querySelectorAll("#rotation-layer-cards form").length === 2);
        await page.screenshot({path: path.join(fixture.screenshots, "imported-shifts.png"), fullPage: true});
        await page.goto("/admin/directory-sync");
        const sourceRow = page.locator("#ds-list tr[data-source-id='" + source.id + "']");
        await sourceRow.waitFor();
        const beforeToggle = await (await page.request.get("/api/admin/directory-sync/" + source.id)).json();
        const managementPosts = [];
        const recordManagementPost = request => {
            if (request.method() === "POST" && /\/directory-sync\/\d+\/(preview|apply|run)$/.test(request.url())) managementPosts.push(request.url());
        };
        page.on("request", recordManagementPost);
        for (const enabled of [true, false]) {
            await sourceRow.locator(".app-action-menu-toggle").click();
            const toggled = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "PUT");
            await page.getByRole("menuitem", {name: enabled ? "Enable schedule" : "Disable schedule", exact: true}).click();
            const response = await toggled;
            assert.equal(response.status(), 200, await response.text());
            const data = await response.json();
            assert.equal(data.enabled, enabled);
            assert.equal(data.approved, true);
            assert.equal(data.last_success_at, beforeToggle.last_success_at);
            assert.deepEqual(data.config, beforeToggle.config);
            await page.waitForFunction(({id, text}) => document.querySelector("#ds-list tr[data-source-id='" + id + "'] td:nth-child(3)")?.textContent === text,
                {id: source.id, text: enabled ? "Periodic synchronization enabled" : "Paused"});
            assert.equal(await modal.isVisible(), false, "schedule toggle does not open configuration");
        }
        page.off("request", recordManagementPost);
        assert.deepEqual(managementPosts, [], "schedule toggles do not submit preview or manual imports");

        await sourceRow.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Delete source", exact: true}).click();
        assert.equal(await page.locator("#ds-remove-mode").inputValue(), "keep");
        assert.match(await page.locator("#ds-remove-hint").textContent(), /saved schedule/);
        await page.locator("#ds-remove-mode").selectOption("delete");
        assert.match(await page.locator("#ds-remove-hint").textContent(), /dependent configuration/);
        const labelBounds = await page.locator("label[for=ds-remove-mode]").boundingBox();
        const choiceBounds = await page.locator("#ds-remove-mode").boundingBox();
        const hintBounds = await page.locator("#ds-remove-hint").boundingBox();
        assert.ok(choiceBounds.y >= labelBounds.y + labelBounds.height, "choice appears below its label");
        assert.ok(hintBounds.y >= choiceBounds.y + choiceBounds.height, "explanation appears below the choice");
        await page.screenshot({path: path.join(fixture.screenshots, "delete-source-options.png"), fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        assert.ok(await page.locator("#app-dialog-modal .app-modal-body").evaluate(element => element.scrollWidth <= element.clientWidth + 2), "delete choice fits the mobile modal");
        await page.screenshot({path: path.join(fixture.screenshots, "delete-source-mobile.png"), fullPage: true});
        await page.setViewportSize({width: 1440, height: 1080});
        await page.locator("#app-dialog-cancel").click();
        assert.equal((await page.request.get("/api/admin/directory-sync/" + source.id)).status(), 200, "cancel keeps the source");
        await sourceRow.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Delete source", exact: true}).click();
        assert.equal(await page.locator("#ds-remove-mode").inputValue(), "keep", "each deletion defaults to keeping data");
        const removed = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + source.id) && r.request().method() === "DELETE");
        await page.locator("#app-dialog-confirm").click();
        const removedResponse = await removed;
        assert.equal(removedResponse.status(), 200, await removedResponse.text());
        assert.equal(removedResponse.request().postDataJSON().data_action, "keep");
        await sourceRow.waitFor({state: "detached"});
        await page.goto("/teams");
        await page.locator("#teams-table tr").filter({hasText: "Platform"}).waitFor();
        await page.goto("/rotations");
        await page.locator("#rotations-table .name-button").first().click();
        await page.locator("#rotation-details-modal").getByRole("button", {name: "Imported schedule", exact: true}).click();
        await page.waitForFunction(() => document.querySelectorAll("#rotation-layer-cards form").length === 2);

        await page.goto("/admin/directory-sync");
        await page.waitForFunction(() => directorySyncOptions !== null);
        await page.locator("#ds-new").click();
        await page.locator("#ds-name").fill("Discard source");
        await page.locator("#ds-save").click();
        await page.waitForFunction(() => directorySyncSource?.name === "Discard source");
        const discardedId = await page.evaluate(() => directorySyncSource.id);
        await page.locator("#ds-close-footer").click();
        await page.locator("#ds-list tr[data-source-id='" + discardedId + "'] .app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: "Delete source", exact: true}).click();
        await page.locator("#ds-remove-mode").selectOption("delete");
        const discarded = page.waitForResponse(r => r.url().endsWith("/api/admin/directory-sync/" + discardedId) && r.request().method() === "DELETE");
        await page.locator("#app-dialog-confirm").click();
        const discardedResponse = await discarded;
        assert.equal(discardedResponse.status(), 200, await discardedResponse.text());
        assert.equal(discardedResponse.request().postDataJSON().data_action, "delete");
        await page.waitForFunction(() => document.querySelector("#ds-list").textContent.includes("No synchronization sources configured"));
        assert.deepEqual(errors, []);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
