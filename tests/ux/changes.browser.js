"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");
const fixture = JSON.parse(process.env.CHANGES_FIXTURE);

async function main() {
    const browser = await chromium.launch({
        headless: true,
        channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    });
    const errors = [];
    async function session(token) {
        const context = await browser.newContext({
            baseURL: fixture.baseUrl,
            viewport: { width: 1440, height: 1050 },
            serviceWorkers: "block",
        });
        await context.addCookies([
            { name: "incidentrelay_jwt", value: token, url: fixture.baseUrl },
            { name: "incidentrelay_locale", value: "en", url: fixture.baseUrl },
        ]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) =>
            new URL(route.request().url()).origin === fixture.baseUrl
                ? route.continue()
                : route.abort(),
        );
        return { context, page };
    }
    try {
        const owner = await session(fixture.ownerToken);
        const page = owner.page;
        await page.goto("/changes");
        await page.locator(".changes-title-link").waitFor();
        assert.equal(await page.locator(".changes-title-link").textContent(), fixture.title);
        assert.equal(await page.locator("#changes-rows script").count(), 0);
        assert.equal(await page.locator("#page-title").textContent(), "Changes");
        const scoped = page.waitForResponse((response) =>
            response.url().includes("scope_team_id=" + fixture.ownerTeamId),
        );
        await page.locator("#global-team-filter").selectOption(String(fixture.ownerTeamId));
        assert.equal((await scoped).status(), 200);
        await page.waitForFunction(
            () =>
                !document.querySelector("#changes-team").disabled &&
                !document.querySelector("#changes-service").disabled,
        );
        await page.locator("#changes-search").fill("no-match");
        await page.locator("#changes-filters button[type=submit]").click();
        await page.waitForFunction(() =>
            document.querySelector("#changes-rows").textContent.includes("No entries"),
        );
        assert.ok(page.url().includes("search=no-match"));
        await page.locator("#changes-reset").click();
        await page.locator(".changes-title-link").waitFor();
        await page.screenshot({
            path: path.join(fixture.screenshotDir, "changes-list.png"),
            fullPage: true,
        });
        await page.locator(".changes-title-link").click();
        await page.locator("#changes-events tr").waitFor();
        assert.ok(page.url().endsWith(fixture.uid));
        assert.equal(await page.locator("#changes-detail-title").textContent(), fixture.title);
        assert.equal(
            await page.locator("#changes-external").getAttribute("rel"),
            "noopener noreferrer",
        );
        assert.match(await page.locator("#changes-events").textContent(), /PRIVATE actor/);
        assert.equal(
            (await page.locator("#changes-services").textContent()).includes(fixture.serviceName),
            false,
        );
        await page.screenshot({
            path: path.join(fixture.screenshotDir, "changes-owner.png"),
            fullPage: true,
        });
        await page.goBack();
        await page.locator(".changes-title-link").waitFor();
        await page.goForward();
        await page.locator("#changes-events tr").waitFor();
        await page.reload();
        await page.locator("#changes-events tr").waitFor();
        const detailUrl = "/api/changes/" + fixture.uid;
        await page.route(
            "**" + detailUrl,
            (route) =>
                route.fulfill({
                    status: 503,
                    contentType: "application/json",
                    body: '{"message":"temporary"}',
                }),
            { times: 1 },
        );
        await page.locator("#changes-detail .changes-reload").click();
        await page.waitForFunction(() =>
            document.querySelector("#changes-message").textContent.includes("Could not load"),
        );
        assert.equal(await page.locator("#changes-detail").isVisible(), false);
        // Refresh remains available after a failed detail request.
        await page.locator("#changes-error-actions .changes-reload").click();
        await page.locator("#changes-events tr").waitFor();
        let release;
        let arrived;
        const held = new Promise((resolve) => {
            arrived = resolve;
        });
        await page.route(
            "**" + detailUrl,
            async (route) => {
                const response = await route.fetch();
                await new Promise((resolve) => {
                    release = resolve;
                    arrived();
                });
                await route.fulfill({ response });
            },
            { times: 1 },
        );
        await page.locator("#changes-detail .changes-reload").click();
        await held;
        await page.locator('.menu-link[href="/incidents"]').click();
        const lateResponse = page.waitForResponse(
            (response) => new URL(response.url()).pathname === detailUrl,
        );
        release();
        await lateResponse;
        assert.equal(await page.locator("#changes-detail-title").textContent(), "");
        assert.equal(await page.locator("#changes-events tr").count(), 0);
        const safe = await session(fixture.readerToken);
        await safe.page.goto("/changes/" + fixture.uid);
        await safe.page.locator("#changes-services tr").waitFor();
        assert.equal(
            await safe.page.locator("#changes-detail-title").textContent(),
            "Related change",
        );
        assert.equal(await safe.page.locator("#changes-events-panel").isVisible(), false);
        assert.equal(await safe.page.locator("#changes-external").isVisible(), false);
        assert.equal(
            (await safe.page.locator("#view-changes").textContent()).includes("PRIVATE"),
            false,
        );
        assert.match(
            await safe.page.locator("#changes-services").textContent(),
            /Visible checkout/,
        );
        await safe.page.screenshot({
            path: path.join(fixture.screenshotDir, "changes-safe.png"),
            fullPage: true,
        });
        await safe.page.setViewportSize({ width: 390, height: 844 });
        await safe.page.screenshot({
            path: path.join(fixture.screenshotDir, "changes-mobile.png"),
            fullPage: true,
        });
        await safe.page.route(
            "**" + detailUrl,
            (route) =>
                route.fulfill({
                    status: 404,
                    contentType: "application/json",
                    body: '{"message":"unavailable"}',
                }),
            { times: 1 },
        );
        await safe.page.locator("#changes-detail .changes-reload").click();
        await safe.page.waitForFunction(() =>
            document.querySelector("#changes-message").textContent.includes("unavailable"),
        );
        assert.equal(await safe.page.locator("#changes-services tr").count(), 0);
        assert.equal(await safe.page.locator("#changes-detail").isVisible(), false);
        assert.deepEqual(errors, []);
        await owner.context.close();
        await safe.context.close();
    } finally {
        await browser.close();
    }
}
main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
