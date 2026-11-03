"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require("playwright");
const fixture = JSON.parse(process.env.SILENCES_FIXTURE);

async function main() {
    const browser = await chromium.launch({
        headless: true,
        channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    });
    try {
        const context = await browser.newContext({
            baseURL: fixture.baseUrl,
            viewport: { width: 1440, height: 1000 },
            serviceWorkers: "block",
        });
        await context.addCookies([
            { name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl },
            { name: "incidentrelay_locale", value: "en", url: fixture.baseUrl },
        ]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.route("**/*", route =>
            new URL(route.request().url()).origin === fixture.baseUrl
                ? route.continue() : route.abort(),
        );
        await page.goto("/silences");
        const row = page.locator("#silences-table tr").filter({ hasText: fixture.name });
        await row.waitFor();
        assert.equal(await page.locator("#silence-details-body").count(), 0);
        const widths = await page.locator("#view-silences .page-layout-grid").evaluate(element => ({
            layout: element.getBoundingClientRect().width,
            table: element.querySelector("section").getBoundingClientRect().width,
        }));
        assert(Math.abs(widths.layout - widths.table) <= 1);
        assert.equal(await row.locator(".silence-name-cell").textContent(),
            fixture.name + "Silence #" + fixture.id);
        assert.equal(await row.locator("script").count(), 0);
        assert.equal(await page.evaluate(() => window.silenceInjected), undefined);
        assert.equal(await row.locator(".silence-reason-cell").textContent(), fixture.reason);
        assert.deepEqual(JSON.parse(await row.locator("code").textContent()), fixture.matchers);
        const content = await row.innerText();
        for (const value of [
            "Production Operations", "production-ops", "Host maintenance",
            "Apply to matching unresolved alerts", "Keep affected alerts silenced", "until ",
        ]) assert(content.includes(value), value);
        const other = page.locator("#silences-table tr").filter({ hasText: fixture.otherName });
        for (const value of ["No preset", "New alerts only", "Reactivate affected alerts", "Disabled"]) {
            assert((await other.innerText()).includes(value), value);
        }
        assert.equal(await other.locator("code").textContent(), "{}");

        // Existing actions still edit the rule and refresh the displayed behavior.
        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
        await page.locator("#silence-form-modal").waitFor({ state: "visible" });
        assert.equal(await page.locator("#silence-reason").inputValue(), fixture.reason);
        await page.locator("#silence-apply-to-existing").uncheck();
        await page.locator("#silence-reactivate-on-end").check();
        const saved = page.waitForResponse(response =>
            response.request().method() === "PUT" &&
            new URL(response.url()).pathname === "/api/silences/" + fixture.id,
        );
        await page.locator("#save-silence").click();
        const response = await saved;
        assert.equal(response.status(), 200, await response.text());
        await row.getByText("New alerts only", { exact: true }).waitFor();
        await row.getByText("Reactivate affected alerts", { exact: true }).waitFor();

        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", { name: "Disable", exact: true }).click();
        await page.locator("#app-dialog-confirm").click();
        await row.getByText("Disabled", { exact: true }).waitFor();
        await row.locator(".app-action-menu-toggle").click();
        await page.getByRole("menuitem", { name: "Enable", exact: true }).click();
        await row.getByText("Active now", { exact: true }).waitFor();

        await page.screenshot({
            path: path.join(fixture.screenshots, "silences-desktop.png"), fullPage: true,
        });
        await page.setViewportSize({ width: 390, height: 844 });
        assert.equal(await page.evaluate(() =>
            document.documentElement.scrollWidth <= innerWidth + 1,
        ), true);
        await page.screenshot({
            path: path.join(fixture.screenshots, "silences-mobile.png"), fullPage: true,
        });
        await page.locator("#silences-search").fill("no matching silence");
        const emptyCell = page.locator("#silences-table tr td");
        await emptyCell.getByText("No silences", { exact: true }).waitFor();
        assert.equal(Number(await emptyCell.getAttribute("colspan")),
            await page.locator(".silences-table th").count());
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
