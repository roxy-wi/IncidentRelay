"use strict";

const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.USER_COLORS_FIXTURE);

async function main() {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    const context = await browser.newContext({baseURL: fixture.baseUrl, locale: "en-GB"});
    await context.addCookies([
        {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
        {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
    ]);
    const page = await context.newPage();
    const errors = [];
    const requests = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
        const path = new URL(response.url()).pathname;
        if (path.startsWith("/api/")) { requests.push(`${response.request().method()} ${path} ${response.status()}`); }
    });
    await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
        ? route.continue() : route.abort());
    async function expectColor(selector, background, foreground) {
        await page.locator(selector).first().waitFor({state: "visible"});
        await page.waitForFunction(({selector, background}) => Array.from(document.querySelectorAll(selector))
            .every(element => getComputedStyle(element).backgroundColor === background), {selector, background});
        if (foreground) {
            assert.equal(await page.locator(selector).first().evaluate(el => getComputedStyle(el).color), foreground);
        }
    }
    try {
        for (const [hex, rgb, text] of [["#ffffff", "rgb(255, 255, 255)", "rgb(0, 0, 0)"], ["#102030", "rgb(16, 32, 48)", "rgb(255, 255, 255)"]]) {
            await page.goto("/profile");
            await page.waitForLoadState("networkidle");
            await page.locator("#profile-color").waitFor({state: "visible"});
            await page.waitForFunction(() => document.querySelector("#profile-username").value !== "");
            await page.locator("#profile-color").fill(hex);
            const saved = page.waitForResponse(r => new URL(r.url()).pathname === "/api/profile" && r.request().method() === "PUT");
            await page.locator("#save-profile-top").click();
            assert.equal((await saved).status(), 200);
            await expectColor("#profile-avatar", rgb, text);
            await expectColor(".topbar-user-avatar", rgb, text);
            await page.reload();
            await expectColor("#profile-avatar", rgb, text);
            await page.screenshot({path: "tests/.tmp/user-color-profile.png", fullPage: true});

            await page.goto(`/incidents/${fixture.incidentId}`);
            for (const selector of ["#incident-participants-list .user-avatar", "#incident-stakeholders-list .user-avatar", "#incident-comments-list .user-avatar", "#incident-details-summary .user-avatar"]) {
                await expectColor(selector, rgb, text);
            }
            await page.locator("#incident-stakeholders-controls .ts-control").click();
            const option = page.locator(`#incident-stakeholders-controls .ts-dropdown [data-value="${fixture.userId}"]`);
            await expectColor(`#incident-stakeholders-controls .ts-dropdown [data-value="${fixture.userId}"] .user-avatar`, rgb, text);
            await option.click();
            await expectColor("#incident-stakeholders-controls .ts-control .user-avatar", rgb, text);
            assert.equal(await page.evaluate(() => window.bad), undefined);
            assert.equal(await page.locator("#incident-participants-list img").count(), 0);
            await page.screenshot({path: "tests/.tmp/user-color-incident.png", fullPage: true});

            await page.goto(`/calendar?team_id=${fixture.teamId}`);
            await expectColor(`.calendar-assignment[data-user-id="${fixture.userId}"]`, rgb, text);
            await page.locator(`.calendar-assignment[data-user-id="${fixture.userId}"]`).first().click();
            await expectColor(".details-avatar.user-avatar", rgb, text);
            await page.screenshot({path: "tests/.tmp/user-color-calendar.png", fullPage: true});
        }
        assert.deepEqual(errors, []);
    } catch (error) {
        console.error("Browser errors:", errors);
        console.error("API responses:", requests);
        await page.screenshot({path: "tests/.tmp/user-color-failure.png", fullPage: true});
        throw error;
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
