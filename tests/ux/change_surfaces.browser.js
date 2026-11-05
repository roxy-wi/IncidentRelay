"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.CHANGE_SURFACES_FIXTURE);

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
        page.on("pageerror", error => errors.push(error.stack || error.message));
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl ? route.continue() : route.abort());
        return page;
    }
    async function save(page) {
        await page.locator("#change-review-note").fill("Reviewed this change <img src=x onerror=unsafe()>");
        await page.locator("#change-review-save").click();
        await page.waitForFunction(() => !document.getElementById("change-review-modal").classList.contains("is-open"));
    }
    async function pickChange(page) {
        await page.locator("#change-review-modal").waitFor({state: "visible"});
        await page.locator("#change-review-target-fields .ts-control input").fill("deployment");
        await page.locator(`#change-review-target-fields .option[data-value="${fixture.uid}"]`).click();
    }
    async function action(page, row, label) {
        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", {name: label, exact: true}).click();
    }
    try {
        const page = await session(fixture.foreignToken);
        await page.goto("/alerts/" + fixture.groupId);
        await page.waitForFunction(id => document.querySelector("[data-related-episodes]").tomselect?.getValue() === String(id), fixture.secondEpisode);
        await page.locator('[data-alert-details-tab="changes"]').click();
        assert.equal(await page.locator("#alert-related-changes tbody tr[data-relation-id]").count(), 0);
        await page.locator("#alert-related-changes .ts-control").click();
        await page.locator(`#alert-related-changes .option[data-value="${fixture.firstEpisode}"]`).click();
        await page.locator("#alert-related-changes tbody tr[data-relation-id]").waitFor();
        assert((await page.locator("#alert-related-changes tbody").innerText()).includes("Mitigation"));
        assert(!(await page.locator("#alert-related-changes").innerText()).includes("PRIVATE"));
        await page.locator("#alert-related-changes .ts-control").click();
        await page.locator(`#alert-related-changes .option[data-value="${fixture.secondEpisode}"]`).click();
        await page.waitForFunction(() => !document.querySelector("#alert-related-changes tr[data-relation-id]"));
        await page.locator("#alert-related-changes [data-related-add]").click();
        await pickChange(page);
        await save(page);
        const alertRow = page.locator("#alert-related-changes tr[data-relation-id]");
        await alertRow.waitFor();
        assert((await alertRow.innerText()).includes("Context"));
        assert.equal(await page.locator("#alert-related-changes img").count(), 0);
        await action(page, alertRow, "Reject");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#alert-related-changes tbody").textContent.includes("Rejected"));
        await page.screenshot({path: path.join(fixture.screenshotDir, "related-alert.png"), fullPage: true});
        await alertRow.locator("a").click();
        await page.locator("#changes-detail-title").waitFor({state: "visible"});
        assert.equal(await page.locator("#alert-details-modal").isVisible(), false);
        assert(!(await page.locator("#changes-detail").innerText()).includes("PRIVATE"));

        await page.goto("/incidents/" + fixture.incidentId);
        await page.locator("#incident-related-changes [data-related-add]").click();
        await pickChange(page);
        await save(page);
        const incidentRow = page.locator("#incident-related-changes tr[data-relation-id]");
        await incidentRow.waitFor();
        await action(page, incidentRow, "Change role");
        await page.locator("#change-review-role").selectOption("mitigation");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#incident-related-changes tbody").textContent.includes("Mitigation"));
        await action(page, incidentRow, "Remove link");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#incident-related-changes tbody").textContent.includes("Removed"));
        await action(page, incidentRow, "Restore link");
        await save(page);
        await page.waitForFunction(() => document.querySelector("#incident-related-changes tbody").textContent.includes("Linked"));
        for (const theme of ["light", "dark"]) {
            await page.evaluate(value => window.AppTheme.apply(value), theme);
            await page.screenshot({path: path.join(fixture.screenshotDir, "related-incident-" + theme + ".png"), fullPage: true});
        }
        await page.setViewportSize({width: 390, height: 844});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No page-wide overflow");
        await page.screenshot({path: path.join(fixture.screenshotDir, "related-incident-mobile.png"), fullPage: true});

        // A delayed response from an old workspace must not reopen or populate it.
        let release;
        const held = new Promise(resolve => { release = resolve; });
        let observed;
        const requested = new Promise(resolve => { observed = resolve; });
        await page.route(`**/api/incidents/${fixture.incidentId}/changes?*`, async route => {
            const result = await route.fetch(); observed(); await held; await route.fulfill({response: result});
        });
        await page.locator("#incident-related-changes [data-related-reload]").click();
        await requested;
        await page.evaluate(() => navigate("/changes", true));
        release();
        await page.waitForLoadState("networkidle");
        assert.equal(await page.locator("#incident-related-changes tbody tr").count(), 0);

        const timeline = await page.request.get(`/api/services/${fixture.serviceId}/timeline`);
        assert.equal(timeline.headers()["cache-control"], "no-store");
        const events = (await timeline.json()).items.filter(event => event.source === "change_intelligence");
        assert.equal(events.length, 1);
        assert(!JSON.stringify(events).includes("PRIVATE"));
        await page.goto("/services");
        await page.waitForFunction(id => !!getServiceById(id), fixture.serviceId);
        await page.evaluate(id => openServiceDetailsModal(id), fixture.serviceId);
        await page.locator(`#service-details-timeline-body a[href="/changes/${fixture.uid}"]`).click();
        await page.locator("#changes-detail-title").waitFor({state: "visible"});
        assert.equal(await page.locator("#service-details-modal").isVisible(), false);
        assert(!(await page.locator("#changes-detail").innerText()).includes("PRIVATE"));

        const owner = await session(fixture.ownerToken);
        await owner.goto("/incidents/" + fixture.incidentId);
        await owner.locator("#incident-related-changes tr[data-relation-id]").waitFor();
        assert((await owner.locator("#incident-related-changes tbody").innerText()).includes("PRIVATE"));
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
