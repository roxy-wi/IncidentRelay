"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.INCIDENT_WORKSPACE_FIXTURE);

async function main() {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    let page;
    const errors = [];
    const failedAssets = [];
    try {
        const context = await browser.newContext({baseURL: fixture.baseUrl, locale: "en-GB", timezoneId: "Europe/Moscow"});
        await context.addCookies([{name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
        page = await context.newPage();
        page.on("pageerror", error => errors.push(error.message));
        page.on("response", response => {
            const path = new URL(response.url()).pathname;
            if (path.startsWith("/static/") && response.status() >= 400) {
                failedAssets.push(`${response.status()} ${path}`);
            }
        });
        // The suite must never send data outside its ephemeral local server.
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        const url = `/incidents/${fixture.incidentId}?search=Workspace&status=declared&page=1&page_size=10`;
        async function ready(locale = "en") {
            const common = JSON.parse(fs.readFileSync(`app/static/i18n/${locale}/common.json`, "utf8"));
            await page.locator("#incident-details-modal").waitFor({state: "visible"});
            await page.locator("#incident-events .event-item").first().waitFor({state: "visible"});
            await page.waitForFunction(loading => !Array.from(document.querySelectorAll("#incident-details-modal .overview-empty"))
                .some(element => element.textContent === loading), common["common.loading"]);
        }
        async function waitForText(selector, text) {
            await page.locator(selector).getByText(text, {exact: false}).first().waitFor({state: "visible"});
        }
        await page.goto(url);
        await ready();
        const activity = page.locator("#incident-events");
        await waitForText("#incident-events", "Resolved → Investigating");
        assert.match(await activity.innerText(), /04:30/);
        assert((await activity.innerText()).includes(fixture.actorName));
        assert.equal(await activity.getByText(`Open AlertGroup #${fixture.groupId}`, {exact: true}).count(), 1);
        await activity.getByText(`Open AlertGroup #${fixture.groupId}`, {exact: true}).click();
        await page.waitForURL(new RegExp(`/alerts/${fixture.groupId}`));
        await page.goBack();
        await ready();

        // The real controls persist data through real endpoints.
        await page.locator("#incident-participant-user").selectOption(String(fixture.userId));
        await page.locator("#incident-participant-role").selectOption("commander");
        await page.locator("#incident-participant-add").click();
        await waitForText("#incident-participants-list", "Commander");
        await page.locator("#incident-workspace-stakeholder-email").fill("external@example.org");
        await page.locator("#incident-stakeholder-add").click();
        await waitForText("#incident-stakeholders-list", "external@example.org");
        await page.locator("#incident-service-select").selectOption(String(fixture.serviceId));
        await page.locator("#incident-service-add").click();
        await waitForText("#incident-services-list", "Current service impact");
        await page.locator("#incident-comment-input").fill("Operational <script>window.bad=1</script>\nSecond line");
        await page.locator("#incident-comment-add").click();
        await waitForText("#incident-comments-list", "Second line");
        assert.equal(await page.evaluate(() => window.bad), undefined);
        await page.locator("#incident-root-cause").fill("Failed dependency");
        await page.locator("#incident-resolution-summary").fill("Dependency restored");
        const resolutionSaved = page.waitForResponse(response => response.request().method() === "PATCH"
            && new URL(response.url()).pathname === `/api/incidents/${fixture.incidentId}`);
        const refreshedActivity = page.waitForResponse(response => new URL(response.url()).pathname === `/api/incidents/${fixture.incidentId}/activity`);
        await page.locator("#incident-resolution-save").click();
        assert.equal((await resolutionSaved).status(), 200);
        await (await refreshedActivity).finished();
        await ready();

        // A stale version leaves the user's draft intact; reload is explicit.
        const saved = await (await context.request.get(`/api/incidents/${fixture.incidentId}`)).json();
        assert.equal(saved.root_cause, "Failed dependency");
        assert.equal(saved.resolution_summary, "Dependency restored");
        const changed = await context.request.patch(`/api/incidents/${fixture.incidentId}`, {
            data: {row_version: saved.row_version, root_cause: "Concurrent update"},
        });
        assert.equal(changed.status(), 200);
        await page.locator("#incident-root-cause").fill("Unsaved draft");
        await page.locator("#incident-resolution-save").click();
        await page.locator("#incident-details-reload").waitFor({state: "visible"});
        assert.equal(await page.locator("#incident-root-cause").inputValue(), "Unsaved draft");
        assert.match(await page.locator("#incident-details-error").innerText(), /text is preserved/);
        await page.locator("#incident-details-reload").click();
        await page.waitForFunction(() => document.querySelector("#incident-root-cause").value === "Concurrent update");

        await page.locator("#close-incident-details").click();
        await page.waitForURL(/\/incidents\?/);
        assert.equal(new URL(page.url()).searchParams.get("search"), "Workspace");
        assert.equal(await page.locator("#incidents-search").inputValue(), "Workspace");
        await page.goBack();
        await ready();
        await page.goForward();
        await page.locator("#incidents-list-view").waitFor({state: "visible"});
        await page.goto(url);
        await ready();
        await page.reload();
        await ready();
        assert.equal(await page.locator("#incident-root-cause").inputValue(), "Concurrent update");

        // Delayed detail success cannot resurrect a workspace after Back.
        let release;
        let received;
        const held = new Promise(resolve => { release = resolve; });
        const requested = new Promise(resolve => { received = resolve; });
        const detailPattern = `**/api/incidents/${fixture.incidentId}`;
        await page.route(detailPattern, async route => {
            if (route.request().method() === "GET") { received(); await held; }
            await route.continue();
        });
        await page.locator("#incident-resolution-save").click();
        await requested;
        await page.locator("#close-incident-details").click();
        const completed = page.waitForResponse(response => response.request().method() === "GET"
            && new URL(response.url()).pathname === `/api/incidents/${fixture.incidentId}`);
        release();
        const delayedDetail = await completed;
        assert.equal(delayedDetail.status(), 200);
        await delayedDetail.finished();
        await page.locator("#incidents-list-view").waitFor({state: "visible"});
        assert.equal(await page.locator("#incident-details-modal").isVisible(), false);
        await page.unroute(detailPattern);

        // Collection failures must be visible and must not render stale content.
        await page.route(`**/api/incidents/${fixture.incidentId}/activity`, route => route.fulfill({
            status: 503, contentType: "application/json", body: JSON.stringify({message: "Activity unavailable"}),
        }));
        await page.goto(url);
        await waitForText("#incident-events", "Activity unavailable");
        await page.unroute(`**/api/incidents/${fixture.incidentId}/activity`);

        // All six locales render actual template and dynamic role translations.
        for (const locale of ["en", "ru", "de", "fr", "es", "zh"]) {
            await context.addCookies([{name: "incidentrelay_locale", value: locale, url: fixture.baseUrl}]);
            await page.goto(url);
            await ready(locale);
            const dictionary = JSON.parse(fs.readFileSync(`app/static/i18n/${locale}/incidents.json`, "utf8"));
            assert.equal(await page.locator("#incident-participants-section h3").innerText(), dictionary["incidents.workspace.participants"]);
            await waitForText("#incident-participants-list", dictionary["incidents.workspace.role.commander"]);
        }
        await context.addCookies([{name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
        await page.goto(url);
        await ready();
        await page.screenshot({path: "tests/.tmp/workspace-desktop.png", fullPage: true});
        await page.locator("#incident-root-cause").focus();
        await page.keyboard.press("Tab");
        assert.equal(await page.locator("#incident-resolution-summary").evaluate(el => el === document.activeElement), true);
        await page.setViewportSize({width: 390, height: 844});
        await page.screenshot({path: "tests/.tmp/workspace-mobile.png", fullPage: true});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
        assert.deepEqual(errors, []);

        for (const selector of ["#incident-participants-list", "#incident-stakeholders-list", "#incident-services-list"]) {
            await page.locator(selector).getByRole("button", {name: "Remove", exact: true}).click();
            await page.waitForFunction(target => document.querySelectorAll(target + " button").length === 0
                && !document.querySelector(target).textContent.includes("Loading..."), selector);
        }

        // Explicit browser timezones, including both sides of the DST fallback.
        for (const [timezone, expected] of [["UTC", [0, 1]], ["Europe/Moscow", [3, 4]], ["Europe/Berlin", [2, 2]]]) {
            const zone = await browser.newContext({timezoneId: timezone, locale: "en-GB"});
            const zonePage = await zone.newPage();
            await zonePage.addScriptTag({path: "app/static/js/core/dates.js"});
            const times = await zonePage.evaluate(() => ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"].map(value => formatDateTimeMinutes(value)));
            times.forEach((time, index) => assert(time.endsWith(String(expected[index]).padStart(2, "0") + ":30")));
            await zone.close();
        }

        await context.addCookies([{name: "incidentrelay_jwt", value: fixture.readerToken, url: fixture.baseUrl}]);
        await page.goto(url);
        await ready();
        assert.equal(await page.locator("#incident-participant-add").isVisible(), false);
        assert.equal(await page.locator("#incident-root-cause").isDisabled(), true);
        assert.equal((await context.request.post(`/api/incidents/${fixture.incidentId}/comments`, {data: {body: "forbidden"}})).status(), 403);
        console.log("Workspace browser scenarios passed");
    } catch (error) {
        console.error("Browser errors:", errors);
        console.error("Failed static assets:", failedAssets);
        if (page) { await page.screenshot({path: "tests/.tmp/workspace-failure.png", fullPage: true}); }
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
