"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.PROFILE_TOKENS_FIXTURE);

async function assertReadable(button) {
    // Wait for the shared button's 140 ms hover/color transitions.
    await button.page().waitForTimeout(180);
    const contrast = await button.evaluate(element => {
        const rgba = value => value.match(/[\d.]+/g).map(Number);
        const style = getComputedStyle(element);
        const text = rgba(style.color);
        const background = rgba(style.backgroundColor);
        const parent = rgba(getComputedStyle(element.closest(".json-editor-header")).backgroundColor);
        const alpha = background[3] ?? 1;
        const blended = background.slice(0, 3).map((value, index) => value * alpha + parent[index] * (1 - alpha));
        const luminance = rgb => rgb.slice(0, 3).map(value => {
            const channel = value / 255;
            return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
        const foregroundLight = luminance(text);
        const backgroundLight = luminance(blended);
        return (Math.max(foregroundLight, backgroundLight) + 0.05) / (Math.min(foregroundLight, backgroundLight) + 0.05);
    });
    assert.ok(contrast >= 4.5, `Copy token text contrast must be at least 4.5, got ${contrast}`);
}

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1280, height: 1000}});
        await context.addCookies([
            {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
        ]);
        // Exercise the real copy handler without changing the host clipboard.
        await context.addInitScript(() => Object.defineProperty(navigator, "clipboard", {
            value: {writeText: value => { window.copiedProfileToken = value; return Promise.resolve(); }},
        }));
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        await page.goto("/profile");
        await page.waitForLoadState("networkidle");
        await page.waitForFunction(() => document.querySelector("#profile-username").value !== "");
        await page.locator('[data-profile-tab="tokens"]').click();
        await page.locator("#open-profile-token-modal").click();
        const button = page.locator("#copy-profile-token");
        assert.equal(await button.isVisible(), false);
        await page.locator("#profile-token-name").fill("Copy contrast regression");
        const generated = page.waitForResponse(response => response.url().endsWith("/api/profile/tokens")
            && response.request().method() === "POST");
        await page.locator("#create-profile-token").click();
        assert.equal((await generated).status(), 201);
        await button.waitFor({state: "visible"});
        for (const theme of ["light", "dark"]) {
            await page.evaluate(value => AppTheme.apply(value), theme);
            await page.mouse.move(0, 0);
            await assertReadable(button);
            await button.hover();
            await assertReadable(button);
            await button.focus();
            await page.keyboard.press("Enter");
            await page.waitForFunction(() => window.copiedProfileToken === document.querySelector("#profile-token-result").value);
            await page.waitForFunction(() => document.querySelector("#profile-token-status").textContent.includes("copied"));
            await assertReadable(button);
            await page.screenshot({path: path.join(fixture.screenshots, `copy-token-${theme}.png`),
                fullPage: true, mask: [page.locator("#profile-token-result")]});
        }
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
