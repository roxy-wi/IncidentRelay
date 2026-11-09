"use strict";

const assert = require("node:assert/strict");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.TEAM_CREATE_FIXTURE);

async function main() {
    const browser = await chromium.launch({
        headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    });
    try {
        const context = await browser.newContext({
            baseURL: fixture.baseUrl, serviceWorkers: "block",
            viewport: {width: 1440, height: 1080},
        });
        await context.addCookies([
            {name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl},
        ]);
        const page = await context.newPage();
        page.setDefaultTimeout(10000);
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl
            ? route.continue() : route.abort());

        for (const [route, object] of [
            ["rotations", "rotation"], ["routes", "route"],
            ["channels", "channel"], ["silences", "silence"],
            ["escalation-policies", "escalation-policy"],
            ["notification-policies", "notification-policy"],
            ["priority-policies", "priority-policy"], ["matcher-presets", "matcher-preset"],
        ]) {
            // A read-only team in the global filter must not clear the form's
            // writable default, particularly when a policy form is reset.
            await page.goto(`/${route}?team=${fixture.readOnlyTeamId}`);
            await page.locator(`#${object}-team option[value='${fixture.teamId}']`).waitFor({state: "attached"});
            await page.locator(`#open-${object}-create-modal`).click();
            const modal = page.locator(`#${object}-form-modal`);
            await modal.waitFor({state: "visible"});
            const options = await page.locator(`#${object}-team option`).evaluateAll(
                nodes => nodes.map(node => node.value).filter(Boolean)
            );
            assert.deepEqual(options, [String(fixture.teamId)], object + " writable targets");
            assert.equal(await page.locator(`#${object}-team`).inputValue(), String(fixture.teamId));

            if (object === "channel") {
                assert.deepEqual(await page.locator("#channel-group option").evaluateAll(
                    nodes => nodes.map(node => node.value).filter(Boolean)
                ), [String(fixture.groupId)], "channel groups must have writable teams");
            }
            if (!["rotation", "route", "channel", "silence"].includes(object)) continue;

            await page.locator(`#${object}-name`).fill("Managed " + object);
            if (object === "rotation") {
                await page.locator("#rotation-start").fill("2026-01-01T09:00");
            } else if (object === "channel") {
                await page.locator("#channel-type").selectOption("webhook");
                await page.locator("#cfg-webhook-url").fill("https://hooks.example.com/incidentrelay");
            } else if (object === "silence") {
                await page.locator("#silence-starts-at").fill("2098-01-01T09:00");
                await page.locator("#silence-ends-at").fill("2098-01-01T10:00");
            }
            const [response] = await Promise.all([
                page.waitForResponse(response => new URL(response.url()).pathname === `/api/${route}`
                    && response.request().method() === "POST"),
                page.locator(`#save-${object}`).click(),
            ]);
            assert.equal(response.status(), 201, object + ": " + await response.text());
            assert.equal((await response.json()).team_id, fixture.teamId);
            await modal.waitFor({state: "hidden"});

            const forbidden = await context.request.post(`/api/${route}`, {
                data: {...response.request().postDataJSON(), team_id: fixture.readOnlyTeamId},
            });
            assert.equal(forbidden.status(), 403, object + " must stay forbidden in a read-only team");
        }

        await page.goto("/teams");
        await page.waitForFunction(() => typeof currentUser !== "undefined" && currentUser);
        assert.equal(await page.locator("#open-team-create-modal").isVisible(), false,
            "team manager must not gain group-level team creation");

        async function switchGroup(groupId) {
            await page.locator("#topbar-profile").click();
            await page.locator("#profile-active-group").selectOption(String(groupId));
            const [response] = await Promise.all([
                page.waitForResponse(response => new URL(response.url()).pathname === "/api/profile/active-group"
                    && response.request().method() === "POST"),
                page.locator("#save-active-group").click(),
            ]);
            assert.equal(response.status(), 200);
            await page.waitForFunction(group => currentUser.active_group_id === group, groupId);
            // Stay in the same SPA session to exercise cached permission invalidation.
            await page.locator("a.menu-link[href='/rotations']").click();
            await page.locator("#rotation-team").waitFor({state: "attached"});
        }
        await switchGroup(fixture.otherGroupId);
        await page.waitForFunction(groupId => currentUser.active_group_id === groupId &&
            document.querySelector("#open-rotation-create-modal").disabled, fixture.otherGroupId);
        assert.equal(await page.locator("#open-rotation-create-modal").isVisible(), false);
        await switchGroup(fixture.groupId);
        await page.locator("#open-rotation-create-modal").waitFor({state: "visible"});
        await page.locator("#open-rotation-create-modal").click();
        assert.equal(await page.locator("#rotation-team").inputValue(), String(fixture.teamId));
        assert.deepEqual(errors, [], "no browser JavaScript errors");
        console.log("All eight create forms and four POSTs passed for group viewer + team manager");
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
