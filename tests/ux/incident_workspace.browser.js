"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.INCIDENT_WORKSPACE_FIXTURE);

async function main() {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    let page;
    try {
        const context = await browser.newContext({baseURL: fixture.baseUrl, locale: "en-GB", timezoneId: "Europe/Moscow"});
        await context.addCookies([{name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
        page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        // The suite must never send data outside its ephemeral local server.
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        const url = `/incidents/${fixture.incidentId}?search=Workspace&status=declared&page=1&page_size=10`;
        async function ready() {
            await page.locator("#incident-details-modal").waitFor({state: "visible"});
            await page.waitForFunction(() => currentIncident && $("#incident-events .event-item").length > 0);
            await page.waitForFunction(() => !$("#incident-details-modal .overview-empty").toArray()
                .some(element => element.textContent === i18n.t("common.loading")));
        }
        await page.goto(url);
        await ready();
        const activity = page.locator("#incident-events");
        await page.waitForFunction(() => $("#incident-events").text().includes("Resolved → Investigating"));
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
        await page.waitForFunction(() => $("#incident-participants-list").text().includes("Commander"));
        await page.locator("#incident-workspace-stakeholder-email").fill("external@example.org");
        await page.locator("#incident-stakeholder-add").click();
        await page.waitForFunction(() => $("#incident-stakeholders-list").text().includes("external@example.org"));
        await page.locator("#incident-service-select").selectOption(String(fixture.serviceId));
        await page.locator("#incident-service-add").click();
        await page.waitForFunction(() => $("#incident-services-list").text().includes("Current service impact"));
        await page.locator("#incident-comment-input").fill("Operational <script>window.bad=1</script>\nSecond line");
        await page.locator("#incident-comment-add").click();
        await page.waitForFunction(() => $("#incident-comments-list").text().includes("Second line"));
        assert.equal(await page.evaluate(() => window.bad), undefined);
        await page.locator("#incident-root-cause").fill("Failed dependency");
        await page.locator("#incident-resolution-summary").fill("Dependency restored");
        await page.locator("#incident-resolution-save").click();
        await page.waitForFunction(() => currentIncident.root_cause === "Failed dependency");

        // A stale version leaves the user's draft intact; reload is explicit.
        const saved = await (await context.request.get(`/api/incidents/${fixture.incidentId}`)).json();
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
        await page.waitForFunction(() => $("#incident-root-cause").val() === "Concurrent update");

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
        await page.route(detailPattern, async route => { received(); await held; await route.continue(); });
        await page.evaluate(() => refreshCurrentIncident());
        await requested;
        await page.locator("#close-incident-details").click();
        const completed = page.waitForResponse(response => response.url().endsWith(`/api/incidents/${fixture.incidentId}`));
        release();
        await completed;
        await page.waitForFunction(() => currentIncident === null);
        assert.equal(await page.locator("#incident-details-modal").isVisible(), false);
        await page.unroute(detailPattern);

        // Collection failures must be visible and must not render stale content.
        await page.route(`**/api/incidents/${fixture.incidentId}/activity`, route => route.fulfill({
            status: 503, contentType: "application/json", body: JSON.stringify({message: "Activity unavailable"}),
        }));
        await page.goto(url);
        await page.waitForFunction(() => $("#incident-events").text().includes("Activity unavailable"));
        await page.unroute(`**/api/incidents/${fixture.incidentId}/activity`);

        // All six locales render actual template and dynamic role translations.
        for (const locale of ["en", "ru", "de", "fr", "es", "zh"]) {
            await context.addCookies([{name: "incidentrelay_locale", value: locale, url: fixture.baseUrl}]);
            await page.goto(url);
            await ready();
            const dictionary = JSON.parse(fs.readFileSync(`app/static/i18n/${locale}/incidents.json`, "utf8"));
            assert.equal(await page.locator("#incident-participants-section h3").innerText(), dictionary["incidents.workspace.participants"]);
            await page.waitForFunction(label => $("#incident-participants-list").text().includes(label), dictionary["incidents.workspace.role.commander"]);
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
            await page.waitForFunction(target => $(target).find("button").length === 0
                && !$(target).text().includes(i18n.t("common.loading")), selector);
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
        if (page) { await page.screenshot({path: "tests/.tmp/workspace-failure.png", fullPage: true}); }
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
