"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.USER_TEAMS_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        const context = await browser.newContext({baseURL: fixture.baseUrl, viewport: {width: 1280, height: 960}});
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());
        async function login(token) {
            await context.addCookies([
                {name: "incidentrelay_jwt", value: token, url: fixture.baseUrl},
                {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
            ]);
        }
        async function assertTeams(selector, ids) {
            await page.waitForFunction(({selector, count}) =>
                document.querySelectorAll(selector + " [data-team-id]").length === count, {selector, count: ids.length});
            const actual = await page.locator(selector + " [data-team-id]").evaluateAll(rows =>
                rows.map(row => Number(row.dataset.teamId)).sort((a, b) => a - b));
            assert.deepEqual(actual, [...ids].sort((a, b) => a - b));
            assert.equal(await page.locator(selector + " img, " + selector + " script").count(), 0);
            assert.equal(await page.evaluate(() => window.bad), undefined);
        }
        await login(fixture.token);
        await page.goto("/profile");
        await page.waitForLoadState("networkidle");
        await assertTeams("#profile-teams", [fixture.sharedId, fixture.ownId]);
        assert.match(await page.locator(`#profile-teams [data-team-id='${fixture.sharedId}']`).textContent(), /Responder/);
        assert.ok((await page.locator("#profile-teams").textContent()).includes(fixture.groupName));
        for (const theme of ["light", "dark"]) {
            await page.evaluate(value => AppTheme.apply(value), theme);
            await page.locator("#profile-teams").scrollIntoViewIfNeeded();
            await page.screenshot({path: path.join(fixture.screenshots, `profile-${theme}.png`)});
        }
        await page.locator("#profile-display-name").fill("Updated profile admin");
        const saved = page.waitForResponse(response => response.url().endsWith("/api/profile")
            && response.request().method() === "PUT");
        await page.locator("#save-profile-top").click();
        assert.equal((await saved).status(), 200);
        await assertTeams("#profile-teams", [fixture.sharedId, fixture.ownId]);
        await page.reload();
        await assertTeams("#profile-teams", [fixture.sharedId, fixture.ownId]);
        await page.setViewportSize({width: 390, height: 844});
        await page.locator("#profile-teams").scrollIntoViewIfNeeded();
        assert.ok(await page.locator("#profile-teams").evaluate(element => element.scrollWidth <= element.clientWidth + 1));
        await page.screenshot({path: path.join(fixture.screenshots, "profile-mobile.png")});

        await login(fixture.emptyToken);
        await page.goto("/profile");
        await page.waitForFunction(() => document.querySelector("#profile-teams").textContent.includes("No teams to display"));
        await assertTeams("#profile-teams", []);

        await login(fixture.token);
        await page.setViewportSize({width: 1280, height: 960});
        await page.goto("/admin/users");
        await page.waitForLoadState("networkidle");
        await page.locator("#admin-users-table .name-button").filter({hasText: fixture.targetName}).click();
        await assertTeams("#admin-user-teams", [fixture.sharedId, fixture.disabledId]);
        assert.ok((await page.locator("#admin-user-teams").textContent()).includes(fixture.disabledName));
        assert.equal(await page.locator("#admin-user-teams .status-inactive").textContent(), "Disabled");
        assert.equal(await page.locator("#admin-user-teams input, #admin-user-teams select").count(), 0);
        await page.locator("#admin-user-teams-section").scrollIntoViewIfNeeded();
        await page.screenshot({path: path.join(fixture.screenshots, "admin-modal.png")});
        await page.setViewportSize({width: 390, height: 844});
        await page.locator("#admin-user-teams-section").scrollIntoViewIfNeeded();
        assert.ok(await page.locator("#admin-user-teams").evaluate(element => element.scrollWidth <= element.clientWidth + 1));
        await page.screenshot({path: path.join(fixture.screenshots, "admin-modal-mobile.png")});
        await page.locator("#close-admin-user-modal").click();
        await page.setViewportSize({width: 1280, height: 960});
        await page.locator("#admin-users-table .name-button").filter({hasText: fixture.emptyName}).click();
        await assertTeams("#admin-user-teams", []);
        assert.match(await page.locator("#admin-user-teams").textContent(), /No teams to display/);
        await page.locator("#close-admin-user-modal").click();
        await page.locator("#new-admin-user").click();
        assert.equal(await page.locator("#admin-user-teams-section").isVisible(), false);
        assert.equal(await page.locator("#admin-user-teams li").count(), 0);
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
