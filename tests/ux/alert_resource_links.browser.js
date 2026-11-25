"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.ALERT_LINKS_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1280, height: 960}});
        await context.addCookies([
            {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "ru", url: fixture.baseUrl},
        ]);
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        await page.goto("/alerts/" + fixture.groupId);
        await page.locator("#alert-primary-details [data-alert-resource='runbook']").waitFor();
        const links = page.locator("#alert-primary-details .alert-primary-links a");
        assert.equal(await links.count(), 3);
        for (const [kind, label] of [["source", "Открыть событие в источнике"], ["dashboard", "Дашборд"], ["runbook", "Ранбук"]]) {
            const link = page.getByRole("link", {name: label, exact: true});
            assert.equal(await link.getAttribute("data-alert-resource"), kind);
            assert.equal(await link.getAttribute("href"), fixture[kind]);
            assert.equal(await link.getAttribute("target"), "_blank");
            assert.equal(await link.getAttribute("rel"), "noopener noreferrer");
            assert.equal(await link.textContent(), label);
            assert.equal(await link.locator(".fa-external-link-alt[aria-hidden='true']").count(), 1);
        }
        for (const theme of ["light", "dark"]) {
            await page.evaluate(value => AppTheme.apply(value), theme);
            await page.locator(".alert-primary-links").scrollIntoViewIfNeeded();
            assert(await links.evaluateAll(nodes => nodes.every(link =>
                getComputedStyle(link.querySelector("span")).textDecorationLine.includes("underline")
                && getComputedStyle(link).color !== getComputedStyle(link.parentElement).color
            )), theme);
            await page.screenshot({path: path.join(fixture.screenshots, `links-${theme}.png`)});
        }
        await page.setViewportSize({width: 390, height: 844});
        await page.locator(".alert-primary-links").scrollIntoViewIfNeeded();
        assert.ok(await page.locator(".alert-primary-links").evaluate(node => node.scrollWidth <= node.clientWidth + 1));
        await page.screenshot({path: path.join(fixture.screenshots, "links-mobile.png")});
        await links.first().focus();
        await page.keyboard.press("Tab");
        assert(await links.nth(1).evaluate(link => link.matches(":focus-visible")
            && getComputedStyle(link).outlineStyle === "solid"));

        // Malformed/unsafe values must not become links even with an unexpected API response.
        await page.evaluate(() => renderAlertPrimaryDetails({
            id: 999, status: "firing", labels: {}, resource_links: [
                {kind: "runbook", url: "javascript:window.bad=1"},
                {kind: "dashboard", url: "https://[invalid"},
                {kind: "source", url: "https://example.test/source"},
                {kind: "source", url: "https://example.test/source"},
                {kind: "constructor", url: "https://example.test/invalid"},
            ]
        }, $("#alert-details-modal")));
        assert.equal(await links.count(), 1);
        assert.equal(await page.evaluate(() => window.bad), undefined);
        await page.evaluate(() => renderAlertPrimaryDetails({id: 999, status: "firing", labels: {}}, $("#alert-details-modal")));
        assert.equal(await links.count(), 0);
        assert.deepEqual(errors, []);
        console.log("Alert source, dashboard and runbook links: desktop, dark, mobile and invalid URL checks passed");
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
