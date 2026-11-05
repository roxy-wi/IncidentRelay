"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");
const fixture = JSON.parse(process.env.CHANGE_REVIEW_FIXTURE);

async function sectionAppearance(section) {
    return section.evaluate(element => {
        const properties = {
            card: ["borderTopColor", "borderTopWidth", "borderTopStyle", "borderRadius", "backgroundColor", "overflow"],
            header: ["backgroundImage", "borderRadius", "padding"],
            footer: ["borderBottomLeftRadius", "borderBottomRightRadius"],
            title: ["fontSize", "fontWeight", "lineHeight", "color", "margin"],
            icon: ["color", "backgroundColor", "borderRadius", "width", "height"],
        };
        const elements = {card: element, header: element.querySelector(".card-header"), footer: element.lastElementChild,
            title: element.querySelector("h3"), icon: element.querySelector(".section-icon")};
        return Object.fromEntries(Object.entries(properties).map(([name, keys]) => {
            const style = getComputedStyle(elements[name]);
            return [name, Object.fromEntries(keys.map(key => [key, style[key]]))];
        }));
    });
}

async function checkSharedSections(page) {
    const expected = {};
    for (const [url, container] of [
        ["/changes/" + fixture.uid, ".changes-detail"],
        ["/incidents/" + fixture.incidentId, ".incidents-workspace"],
    ]) {
        await page.goto(url);
        for (const theme of ["light", "dark"]) {
            await page.evaluate(value => window.AppTheme.apply(value), theme);
            for (const kind of ["services", "alerts", "history"]) {
                const section = page.locator(`${container} .workspace-section[data-section="${kind}"]`);
                await section.waitFor({state: "visible"});
                await page.mouse.move(0, 0);
                const normal = await sectionAppearance(section);
                const key = theme + ":" + kind;
                if (expected[key]) assert.deepEqual(normal, expected[key], "Shared appearance: " + key);
                else expected[key] = normal;
                await section.locator(".card-header").hover();
                const hovered = await sectionAppearance(section);
                assert.equal(hovered.card.borderTopColor, normal.card.borderTopColor, "Keep accent on hover: " + key);
                await page.mouse.move(0, 0);
                // Section appearance must not depend on either page's layout stylesheet.
                await page.evaluate(() => {
                    for (const sheet of document.styleSheets) {
                        if (/\/(changes|incidents)\.css(?:\?|$)/.test(sheet.href || "")) sheet.disabled = true;
                    }
                });
                try {
                    assert.deepEqual(await sectionAppearance(section), normal, "Shared CSS is sufficient: " + key);
                } finally {
                    await page.evaluate(() => {
                        for (const sheet of document.styleSheets) sheet.disabled = false;
                    });
                }
            }
        }
    }
    await page.goto("/changes/" + fixture.uid);
    await page.locator("#changes-correlations tr[data-relation-id]").first().waitFor();
}

async function checkRelationColumns(page) {
    for (const width of [2240, 1440, 390]) {
        await page.setViewportSize({width, height: 1050});
        const positions = await page.locator(".change-relations-table").evaluateAll(tables => tables.map(table => {
            const left = table.getBoundingClientRect().left;
            return Array.from(table.querySelectorAll("thead th")).slice(0, 3)
                .map(cell => cell.getBoundingClientRect().left - left);
        }));
        assert.equal(positions.length, 4);
        for (const columns of positions) {
            columns.forEach((left, index) => assert(Math.abs(left - positions[0][index]) < 1,
                `Relation columns must align at ${width}px: ${JSON.stringify(positions)}`));
        }
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
            "Wide relation tables must scroll inside their cards on mobile");
        if (width === 2240) {
            await page.locator("#changes-detail").screenshot({
                path: path.join(fixture.screenshotDir, "change-aligned-columns.png"),
                animations: "disabled",
            });
        }
    }
    await page.setViewportSize({width: 1440, height: 1050});
}

async function main() {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const errors = [];
    async function session(token) {
        const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1440, height: 1050}, serviceWorkers: "block"});
        await context.addCookies([
            {name: "incidentrelay_jwt", value: token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
        ]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        page.on("pageerror", (error) => errors.push(error.stack || error.message));
        await page.route("**/*", (route) => new URL(route.request().url()).origin === fixture.baseUrl ? route.continue() : route.abort());
        await page.goto("/changes/" + fixture.uid);
        await page.locator("#changes-correlations tr[data-relation-id]").first().waitFor();
        return page;
    }
    async function action(page, row, label) {
        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: label, exact: true}).click();
        await page.locator("#change-review-note").fill("Checked <img src=x onerror=unsafe()>");
    }
    async function save(page) {
        await page.locator("#change-review-save").click();
        await page.waitForFunction(() => !document.querySelector("#change-review-modal").classList.contains("is-open"));
    }
    async function checkConflictGuidance(page, row, endpoint) {
        const cases = [
            ["relation_exists", "already has a relation", "Set manual relation"],
            ["relation_changed", "already been reviewed", "current decision"],
            ["suggestion_stale", "no longer current", "wait for recalculation"],
            ["evidence_changed", "has been recalculated", "updated evidence"],
            ["incident_role_conflict", "different role", "Change role"],
            ["incident_link_removed", "has been removed", "Restore link"],
            ["incident_link_changed", "has changed", "current role and status"],
            ["incident_link_missing", "no longer exists", "Link Incident"],
            ["incident_changed", "updated by another request", "current state"],
            ...[undefined, "future_reason", "__proto__", '<img src=x onerror="unsafe()">']
                .map(reason => [reason, "without a recognized reason", "current relation"]),
        ];
        const pattern = "**" + endpoint;
        let reason;
        await page.route(pattern, route => route.request().method() === "PATCH"
            ? route.fulfill({status: 409, contentType: "application/json", body: JSON.stringify({
                error: "conflict", reason, message: "<img src=x onerror=unsafe()>",
            })}) : route.continue());
        try {
            for (const [code, cause, recovery] of cases) {
                reason = code;
                await action(page, row, "Change role");
                assert.equal(await page.locator("#change-review-error").isVisible(), false);
                await page.locator("#change-review-save").click();
                await page.waitForFunction(text => document.querySelector("#change-review-error").textContent.includes(text), cause);
                const text = await page.locator("#change-review-error").innerText();
                assert(text.includes(recovery), text);
                assert(text.includes("Reload"), text);
                assert(!/\{\w+\}/.test(text), text);
                assert.equal(await page.locator("#change-review-error img").count(), 0);
                assert.equal(await page.locator("#change-review-save").isDisabled(), true);
                assert.equal(await page.locator("#change-review-note").inputValue(), "Checked <img src=x onerror=unsafe()>");
                if (code === "incident_role_conflict") {
                    for (const theme of ["light", "dark"]) {
                        await page.evaluate(value => window.AppTheme.apply(value), theme);
                        const style = await page.locator("#change-review-error").evaluate(element => {
                            const css = getComputedStyle(element);
                            return {color: css.color, background: css.backgroundColor,
                                border: css.borderLeftWidth, role: element.getAttribute("role")};
                        });
                        const [red, green, blue] = style.color.match(/\d+/g).map(Number);
                        assert(red > green && red > blue, theme + " error must be red");
                        assert.notEqual(style.background, "rgba(0, 0, 0, 0)");
                        assert.equal(style.border, "4px");
                        assert.equal(style.role, "alert");
                        await page.screenshot({path: path.join(fixture.screenshotDir, `change-conflict-${theme}.png`)});
                    }
                    await page.setViewportSize({width: 390, height: 844});
                    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
                    await page.screenshot({path: path.join(fixture.screenshotDir, "change-conflict-mobile.png")});
                    await page.setViewportSize({width: 1440, height: 1050});
                    await page.evaluate(() => window.AppTheme.apply("system"));
                }
                await page.locator("#change-review-cancel").click();
            }
        } finally {
            await page.unroute(pattern);
        }
    }
    try {
        const page = await session(fixture.ownerToken);
        await checkSharedSections(page);
        await page.locator("#changes-references .ui-status-badge").first().waitFor();
        await checkRelationColumns(page);
        assert((await page.locator("#changes-references").innerText()).includes(fixture.serviceName));
        assert.equal(await page.locator("#changes-services-pagination").innerText(), "Linked services: 1");
        assert.equal(await page.locator("#changes-services-next").isVisible(), false);
        assert.match(await page.locator("#changes-references-pagination").innerText(), /27 · Page 1 of 2/);
        await page.locator("#changes-references-next").click();
        await page.waitForFunction(() => document.querySelector("#changes-references-pagination").textContent.includes("Page 2 of 2"));
        assert.equal(await page.locator("#changes-references tr").count(), 2);
        assert((await page.locator("#changes-services").innerText()).includes(fixture.serviceName));
        assert.equal(await page.locator("#changes-services-pagination").innerText(), "Linked services: 1");
        assert.equal(await page.locator("#changes-services .ui-status-badge").count(), 2);
        const candidate = page.locator('#changes-correlations tr[data-relation-id="' + fixture.correlationId + '"]');
        await action(page, candidate, "Confirm");
        assert.equal(await page.locator("#change-review-role").inputValue(), "confirmed_cause");
        await save(page);
        await page.waitForFunction((id) => document.querySelector('#changes-correlations tr[data-relation-id="' + id + '"] td:nth-child(3)').textContent === "Confirmed", fixture.correlationId);
        await action(page, candidate, "Reject");
        await save(page);
        await page.waitForFunction((id) => document.querySelector('#changes-correlations tr[data-relation-id="' + id + '"] td:nth-child(3)').textContent === "Rejected", fixture.correlationId);
        assert.equal(await page.locator("#changes-correlations img").count(), 0);

        await page.locator("#changes-add-episode").click();
        const options = page.locator('#change-review-target-fields .ts-dropdown-content .option[role="option"]');
        await options.first().waitFor();
        assert.equal(await options.count(), 25);
        assert.equal(await page.locator("#change-review-target-pagination").count(), 0);
        const gap = await page.locator("#change-review-target-fields").evaluate(element =>
            element.getBoundingClientRect().top - document.querySelector("#change-review-modal .app-modal-header").getBoundingClientRect().bottom);
        assert(gap <= 20 && gap >= 0, "The target picker should sit directly below the modal header");
        await page.locator("#change-review-target-fields .ts-dropdown-content").evaluate(element => { element.scrollTop = element.scrollHeight; });
        await page.locator('#change-review-target-fields .option[data-value="' + fixture.episodeId + '"]').waitFor();
        await page.screenshot({path: path.join(fixture.screenshotDir, "change-episode-picker.png"), fullPage: true});
        await page.locator('#change-review-target-fields .option[data-value="' + fixture.episodeId + '"]').click();
        await page.locator("#change-review-role").selectOption("mitigation");
        await page.locator("#change-review-note").fill("The later rollback restored service");
        await save(page);
        await page.waitForFunction(() => document.querySelectorAll("#changes-correlations tr[data-relation-id]").length === 2);
        assert.match(await page.locator("#changes-correlations").textContent(), /Mitigation/);

        // An older unfiltered response must not erase the latest title search.
        let release;
        let requested;
        const held = new Promise(resolve => { release = resolve; });
        const started = new Promise(resolve => { requested = resolve; });
        const pattern = "**/api/incidents?**";
        await page.route(pattern, async route => {
            if (new URL(route.request().url()).searchParams.get("search") === "") { requested(); await held; }
            await route.continue();
        });
        await page.locator("#changes-add-incident").click();
        await started;
        const search = page.locator("#change-review-target-fields .ts-control input");
        await search.fill("Checkout");
        const match = page.locator('#change-review-target-fields .option[data-value="' + fixture.incidentId + '"]');
        await match.waitFor();
        const stale = page.waitForResponse(response => new URL(response.url()).pathname === "/api/incidents"
            && new URL(response.url()).searchParams.get("search") === "");
        release();
        await (await stale).finished();
        await match.waitFor();
        assert.equal(await options.count(), 1);
        await match.click();
        await page.unroute(pattern);
        await page.locator("#change-review-note").fill("Relevant to the incident");
        await save(page);
        const linked = page.locator("#changes-incident-links tr[data-relation-id]");
        await linked.waitFor();
        await action(page, linked, "Change role");
        await page.locator("#change-review-role").selectOption("mitigation");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#changes-incident-links td:nth-child(2)").textContent === "Mitigation");

        const linkId = await linked.getAttribute("data-relation-id");
        const endpoint = "/api/incidents/" + fixture.incidentId + "/changes/" + linkId;
        const concurrent = await page.request.patch(endpoint, {
            headers: {Authorization: "Bearer " + fixture.ownerToken},
            data: {row_version: 2, relation_type: "confirmed_cause", note: "Another operator's decision"},
        });
        assert.equal(concurrent.status(), 200);
        await action(page, linked, "Remove link");
        await page.locator("#change-review-save").click();
        await page.waitForFunction(() => document.querySelector("#change-review-error").textContent.includes("changed"));
        assert.equal(await page.locator("#change-review-save").isDisabled(), true);
        await page.locator("#change-review-cancel").click();
        await page.locator("#changes-detail .changes-reload").click();
        await page.waitForFunction(() => document.querySelector("#changes-incident-links td:nth-child(2)")?.textContent === "Confirmed cause");
        await action(page, linked, "Remove link");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#changes-incident-links td:nth-child(3)").textContent === "Removed");
        await action(page, linked, "Restore link");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#changes-incident-links td:nth-child(3)").textContent === "Linked");

        await checkConflictGuidance(page, linked, endpoint);
        const colors = await page.locator(".changes-detail .section-icon").evaluateAll(elements => elements.map(element => getComputedStyle(element).color));
        assert.equal(new Set(colors).size, 5);
        // Keep the overview screenshots compact; the long-reference paging was checked above.
        await page.locator("#changes-references-next").click();
        await page.waitForFunction(() => document.querySelector("#changes-references-pagination").textContent.includes("Page 2 of 2"));
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({path: path.join(fixture.screenshotDir, "change-reviews-light.png"), fullPage: true});
        await page.emulateMedia({colorScheme: "dark"});
        await page.waitForFunction(() => document.documentElement.dataset.colorScheme === "dark");
        await page.screenshot({path: path.join(fixture.screenshotDir, "change-reviews-dark.png"), fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        await action(page, linked, "Change role");
        await page.screenshot({path: path.join(fixture.screenshotDir, "change-review-mobile.png"), fullPage: true});
        await page.locator("#change-review-cancel").click();
        await page.locator("#changes-add-incident").click();
        await options.first().waitFor();
        await page.screenshot({path: path.join(fixture.screenshotDir, "change-incident-picker-mobile.png"), fullPage: true});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
        await page.locator("#change-review-cancel").click();
        await page.route(pattern, route => route.fulfill({status: 503, contentType: "application/json", body: "{}"}));
        await page.locator("#changes-add-incident").click();
        await page.waitForFunction(() => document.querySelector("#change-review-error").textContent.length > 0);
        assert.equal(await page.locator("#change-review-save").isDisabled(), true);
        assert.equal(await options.count(), 0);
        await page.locator("#change-review-cancel").click();
        await page.unroute(pattern);
        const viewer = await session(fixture.viewerToken);
        assert.equal(await viewer.locator("#changes-correlations .app-action-menu-toggle").count(), 0);
        assert.equal(await viewer.locator("#changes-incident-links .app-action-menu-toggle").count(), 0);
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
