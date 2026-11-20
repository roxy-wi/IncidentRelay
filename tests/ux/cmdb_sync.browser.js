"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");
const fixture = JSON.parse(process.env.CMDB_SYNC_FIXTURE);

(async () => {
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        const context = await browser.newContext({viewport: {width: 1440, height: 1050}, serviceWorkers: "block"});
        await context.addCookies([{name: "incidentrelay_jwt", value: fixture.token, url: fixture.baseUrl},
            {name: "incidentrelay_locale", value: "en", url: fixture.baseUrl}]);
        await context.route("**/*", route => new URL(route.request().url()).origin === fixture.baseUrl ? route.continue() : route.abort());
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(fixture.baseUrl + "/admin/directory-sync");
        await page.waitForFunction(() => directorySyncOptions !== null);
        await page.locator("#ds-new").click();
        await page.locator("#ds-type").selectOption("jira_assets");
        await page.locator("#ds-name").fill("CMDB browser import");
        await page.locator("#ds-group").selectOption(String(fixture.groupId));
        await page.locator("#cmdb-services-query").fill('objectType = "Machine"');
        await page.locator("#cmdb-business_services-query").fill('objectType = "Application"');
        assert.equal(await page.locator("#ds-operations").isVisible(), false);
        await page.locator("#ds-save").click();
        await page.waitForFunction(() => !document.querySelector("#ds-inspect").disabled);
        await page.locator("#ds-inspect").click();
        await page.locator("#ds-inspect .ui-loading-spinner").waitFor({state: "visible"});
        await page.waitForFunction(() => document.querySelector("#cmdb-team-11") && !document.querySelector("#ds-inspect").disabled);
        await page.locator("#cmdb-services-owner_team_attribute").selectOption("1");
        await page.locator("#cmdb-business_services-owner_team_attribute").selectOption("7");
        await page.locator("#ds-save").click();
        await page.waitForFunction(() => !document.querySelector("#ds-preview").disabled);
        await page.locator("#ds-preview").click();
        await page.waitForFunction(() => !document.querySelector("#ds-preview").disabled && !document.querySelector("#cmdb-issues").hidden);
        assert.equal(await page.locator("#ds-apply").isDisabled(), true);
        assert.equal(await page.locator("#cmdb-issues li").count(), 2);
        for (const externalId of ["11", "12"]) {
            const select = page.locator("#cmdb-team-" + externalId);
            const label = await select.locator(`option[value="${fixture.teams[externalId]}"]`).textContent();
            const inputId = await select.evaluate(element => element.tomselect.control_input.id);
            const input = page.locator("#" + inputId);
            await input.fill(label);
            await page.waitForFunction(({externalId, value}) =>
                document.querySelector("#cmdb-team-" + externalId).tomselect.activeOption?.dataset.value === String(value),
            {externalId, value: fixture.teams[externalId]});
            await input.press("Enter");
            assert.equal(await select.inputValue(), String(fixture.teams[externalId]));
        }
        await page.locator("#ds-enabled").check();
        await page.locator("#ds-save").click();
        await page.waitForFunction(() => !document.querySelector("#ds-preview").disabled);
        await page.locator("#ds-preview").click();
        await page.waitForFunction(() => !document.querySelector("#ds-apply").disabled);
        assert.equal(await page.locator("#ds-preview-table tr").count(), 3);
        await page.screenshot({path: path.join(fixture.screenshots, "preview.png"), fullPage: true});
        await page.locator("#ds-apply").click();
        await page.waitForFunction(() => !document.querySelector("#ds-run").disabled);
        assert.equal(await page.locator("#ds-enabled").isChecked(), true);
        await page.locator("#ds-interval").fill("7200");
        await page.locator("#ds-save").click();
        await page.waitForFunction(() => !document.querySelector("#ds-editor").classList.contains("is-open"));
        assert.match(await page.locator("#ds-list").innerText(), /CMDB browser import/);
        const sourceId = await page.locator("#ds-list tr").filter({hasText: "CMDB browser import"}).getAttribute("data-source-id");
        await page.evaluate(id => editDirectorySync(Number(id)), sourceId);
        await page.waitForFunction(() => document.querySelector("#ds-editor").classList.contains("is-open"));
        assert.equal(await page.locator("#cmdb-team-11").inputValue(), String(fixture.teams["11"]));
        assert.equal(await page.locator("#ds-workflow").getAttribute("data-step"), "saved");
        await page.setViewportSize({width: 390, height: 844});
        await page.screenshot({path: path.join(fixture.screenshots, "mobile.png"), fullPage: true});
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        assert.equal(overflow, false, "mobile page must not overflow horizontally");
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
