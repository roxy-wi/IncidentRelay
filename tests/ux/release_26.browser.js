"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.RELEASE_26_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1440, height: 1080}, serviceWorkers: "block"});
    await context.addCookies([
        {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
        {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
    ]);
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl ? route.continue() : route.abort());
    async function count(selector, expected) {
        await page.waitForFunction(({selector, expected}) => document.querySelectorAll(selector).length === expected, {selector, expected});
    }
    async function centeredHealth() {
        await page.locator(".view-visible .oncall-health-indicator").first().waitFor();
        const cells = await page.locator(".view-visible td.oncall-health-cell").evaluateAll(elements => elements.map(cell => {
            const button = cell.querySelector("button").getBoundingClientRect();
            const bounds = cell.getBoundingClientRect();
            return {x: Math.abs(button.x + button.width / 2 - bounds.x - bounds.width / 2),
                y: Math.abs(button.y + button.height / 2 - bounds.y - bounds.height / 2)};
        }));
        assert.ok(cells.length > 0);
        assert.ok(cells.every(cell => cell.x < 2 && cell.y < 2), JSON.stringify(cells));
        assert.equal(await page.locator(".view-visible th.oncall-health-th").evaluate(el => getComputedStyle(el).textAlign), "center");
    }
    try {
        for (const [name, search] of [
            ["teams", "Roster"], ["rotations", "Schedule"],
            ["services", "Workload"], ["business-services", "Product"],
        ]) {
            const serviceList = name === "services" || name === "business-services";
            const serverList = serviceList || name === "teams";
            const catalogRequests = [];
            const teamHealthRequests = [];
            function recordCatalogRequest(request) {
                const url = new URL(request.url());
                if (url.pathname === "/api/oncall-health/teams/summaries") teamHealthRequests.push(url);
                if (url.pathname !== "/api/" + name) return;
                // The global team selector still loads its own active-team list.
                if (name !== "teams" || url.searchParams.has("include_inactive") || url.searchParams.has("page")) {
                    catalogRequests.push(url.searchParams);
                }
            }
            if (serverList) page.on("request", recordCatalogRequest);
            await page.goto("/" + name);
            await count("#" + name + "-table > tr", 25);
            const pager = "#" + name + "-pagination";
            assert.equal(await page.locator(pager + "-filtered-count").textContent(), "27");
            assert.equal(await page.locator(pager).evaluate(el => el.parentElement.tagName),
                name === "services" ? "DIV" : "SECTION", "footer sits outside the table wrapper");
            assert.ok(await page.locator(pager).evaluate(el => el.previousElementSibling.matches(".table-wrapper")));
            if (!serviceList) await centeredHealth();
            const nextResponse = serverList && page.waitForResponse(response => {
                const url = new URL(response.url());
                return url.pathname === "/api/" + name && url.searchParams.get("page") === "2";
            });
            await page.locator(pager + "-next-page").click();
            await count("#" + name + "-table > tr", 2);
            if (serverList) {
                const payload = await (await nextResponse).json();
                assert.equal(payload.items.length, 2);
                assert.equal(payload.pagination.total_items, 27);
                if (name === "teams") assert.ok(payload.items.every(team => team.health.partial));
            }
            if (name === "rotations") {
                await page.waitForFunction(() => Array.from(document.querySelectorAll("#rotations-table > tr")).every(row =>
                    row.querySelector("[data-rotation-health-id]")?.dataset.rotationHealthId === row.dataset.rotationId));
            }
            assert.equal(await page.locator(pager + "-page-from").textContent(), "26");
            assert.equal(await page.locator(pager + "-next-page").isDisabled(), true);
            if (serverList) {
                const [filter, value] = {
                    teams: ["#teams-status-filter", "active"],
                    services: ["#services-criticality-filter", "medium"],
                    "business-services": ["#business-services-public-filter", "private"],
                }[name];
                await page.locator(filter).selectOption(value);
                await count("#" + name + "-table > tr", 25);
                assert.equal(await page.locator(pager + "-current-page").textContent(), "1");
                assert.equal(await page.locator("#" + name + "-total-count").textContent(), "27");
                await page.locator(pager + "-next-page").click();
                await count("#" + name + "-table > tr", 2);
                await page.locator("#" + name + "-search").fill(search);
                await count("#" + name + "-table > tr", 25);
                assert.equal(await page.locator(pager + "-current-page").textContent(), "1");
            }
            await page.locator("#" + name + "-search").fill(search + " 26");
            await count("#" + name + "-table > tr", 1);
            assert.equal(await page.locator(pager + "-current-page").textContent(), "1");
            assert.match(await page.locator("#" + name + "-table").textContent(), /26/);
            await page.locator("#" + name + "-search").fill("not-a-match");
            await page.locator(pager).waitFor({state: "hidden"});
            await page.locator("#" + name + "-search").fill("");
            await page.locator(pager + "-page-size").selectOption("10");
            await count("#" + name + "-table > tr", 10);
            await page.locator(pager + "-next-page").click();
            const previousRow = await page.locator("#" + name + "-table > tr").first().elementHandle();
            await page.locator("#reload-" + name).click();
            await page.waitForFunction(row => !row.isConnected, previousRow);
            await page.waitForFunction(prefix => document.querySelector(prefix + "-current-page").textContent === "2", pager);
            assert.equal(await page.locator(pager).count(), 1);
            if (!serviceList) await centeredHealth();
            await page.screenshot({path: path.join(fixture.screenshots, name + ".png"), fullPage: true});
            if (name === "teams") {
                const group = await page.locator("#teams-group-filter option").nth(1).getAttribute("value");
                await page.goto("/teams?group=" + encodeURIComponent(group) + "&search=Roster%2026");
                await count("#teams-table .team-name", 1);
                assert.equal(await page.locator("#teams-group-filter").inputValue(), group);
                assert.ok(catalogRequests.some(params => params.get("group") === group && params.get("search") === "Roster 26"));
                assert.equal(teamHealthRequests.length, 0);
            }
            if (serverList) {
                page.off("request", recordCatalogRequest);
                assert.ok(catalogRequests.every(params => params.has("page") && params.has("page_size")));
                assert.ok(catalogRequests.some(params => params.get("search") === search + " 26"));
            }
            if (name === "services") {
                const lookup = await page.request.get("/api/services?page=1&search=Workload%2026");
                const target = (await lookup.json()).items[0];
                await page.goto("/services?service_id=" + target.id);
                await page.locator("#service-details-modal").waitFor();
                await page.waitForFunction(name =>
                    document.querySelector("#service-details-modal-title").textContent.includes(name), target.name);
                await page.locator("#close-service-details-modal").click();
                await page.locator('[data-services-tab="links"]').click();
                await page.locator("#open-service-link-create-modal").click();
                await page.locator("#service-link-modal").waitFor();
                assert.equal(await page.locator("#service-link-service option[value='" + target.id + "']").count(), 1);
            }
        }
        await page.goto("/calendar");
        await count("#calendar-grid > .rotation-calendar-block", 10);
        assert.equal(await page.locator("#calendar-pagination-filtered-count").textContent(), "27");
        assert.equal(await page.locator("#calendar-pagination").evaluate(el => el.parentElement.tagName), "SECTION");
        await page.locator("#calendar-pagination-next-page").click();
        assert.equal(await page.locator("#calendar-pagination-current-page").textContent(), "2");
        await page.locator("#calendar-pagination-next-page").click();
        await count("#calendar-grid > .rotation-calendar-block", 7);
        await page.locator("#calendar-search").fill("Schedule 26");
        await count("#calendar-grid > .rotation-calendar-block", 1);
        assert.equal(await page.locator("#calendar-pagination-current-page").textContent(), "1");
        await page.locator("#calendar-search").fill("no-such-schedule");
        await count("#calendar-grid > .rotation-calendar-block", 0);
        assert.equal(await page.locator("#calendar-pagination").isVisible(), false);
        await page.locator("#calendar-search").fill("");
        await page.locator("#calendar-pagination-page-size").selectOption("25");
        await count("#calendar-grid > .rotation-calendar-block", 25);
        await page.locator("#calendar-pagination-next-page").click();
        await count("#calendar-grid > .rotation-calendar-block", 2);
        const before = await page.locator("#calendar-start").inputValue();
        await page.locator("#calendar-next").click();
        await page.waitForFunction(value => document.querySelector("#calendar-start").value !== value, before);
        await page.locator("#calendar-pagination").waitFor({state: "visible"});
        await count("#calendar-grid > .rotation-calendar-block", 2);
        await page.screenshot({path: path.join(fixture.screenshots, "calendar.png"), fullPage: true});
        await page.setViewportSize({width: 390, height: 844});
        const pagerBounds = await page.locator("#calendar-pagination").boundingBox();
        assert.ok(pagerBounds.x >= 0 && pagerBounds.x + pagerBounds.width <= 392);
        await page.screenshot({path: path.join(fixture.screenshots, "calendar-mobile.png"), fullPage: true});
        await page.setViewportSize({width: 1440, height: 1080});
        const teamOption = page.locator("#global-team-filter option").filter({hasText: "Roster 26"});
        await page.locator("#global-team-filter").selectOption(await teamOption.getAttribute("value"));
        await page.locator("#calendar-grid .calendar-month-grid").waitFor();
        await count("#calendar-grid > .rotation-calendar-block", 1);
        assert.equal(await page.locator("#calendar-pagination").isVisible(), false, "monthly view keeps the selected rotation");
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
