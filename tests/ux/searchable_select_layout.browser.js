"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const root = path.resolve(__dirname, "../..");
const screenshots = path.join(root, "tests/.tmp/searchable-select-layout");

(async () => {
    fs.mkdirSync(screenshots, {recursive: true});
    const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
    try {
        for (const width of [1440, 390]) {
            for (const theme of ["light", "dark"]) {
                const page = await browser.newPage({viewport: {width, height: 720}});
                const errors = [];
                page.on("pageerror", error => errors.push(error.message));
                const options = Array.from({length: 40}, (_, i) => `<option value="${i}">Action ${i}</option>`).join("");
                await page.setContent(`<html data-color-scheme="${theme}"><body class="md-theme">
                    <select id="filter" data-table-single-select>${options}</select>
                    <select id="global">${options}</select>
                    <div id="modal" class="app-modal is-open"><div class="app-modal-dialog app-modal-dialog-wide">
                        <div class="app-modal-header"><h2>Edit rule</h2></div>
                        <div class="app-modal-body"><div style="height: 700px">Rule conditions</div>
                            <section class="card"><div class="card-header"><h2>Actions</h2></div>
                                <div class="orchestration-action-editor"><div class="orchestration-action-row">
                                    <select id="action">${options}</select>
                                    <input class="input" value="Production grouping">
                                    <select class="input"><option>Continue</option></select><button>&times;</button>
                                </div></div>
                            </section>
                        </div><div class="app-modal-footer"><button class="btn">Cancel</button><button class="btn btn-primary">Save rule</button></div>
                    </div></div></body></html>`);
                for (const file of ["material.css", "orchestrations.css", "vendor/tom-select/tom-select.css", "table_filters.css", "theme_dark.css"]) {
                    await page.addStyleTag({path: path.join(root, "app/static/css", file)});
                }
                for (const file of ["vendor/jquery-3.7.1.min.js", "vendor/tom-select.complete.min.js", "core/selects.js", "core/table_filters.js"]) {
                    await page.addScriptTag({path: path.join(root, "app/static/js", file)});
                }
                await page.evaluate(() => {
                    window.i18n = {t: key => key};
                    initTableMultiSelects(document);
                    initSearchableSelect("#global");
                    initSearchableSelect("#action");
                });
                const styles = await page.evaluate(() => ["filter", "global", "action"].map(id => {
                    const picker = document.getElementById(id).tomselect;
                    const control = getComputedStyle(picker.control);
                    const menu = getComputedStyle(picker.dropdown);
                    return [control.minHeight, control.borderRadius, control.borderColor, control.backgroundColor,
                        control.padding, menu.borderRadius, menu.backgroundColor, menu.boxShadow];
                }));
                assert.deepEqual(styles[1], styles[0], "new fields must match alert filters");
                assert.deepEqual(styles[2], styles[0], "modal fields must match alert filters");
                await page.locator("#modal .ts-control").click();
                await page.locator("#action-ts-dropdown").waitFor({state: "visible"});
                const geometry = await page.locator("#action").evaluate(el => {
                    const picker = el.tomselect;
                    const rect = picker.dropdown.getBoundingClientRect();
                    const content = picker.dropdown_content.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
                        controlTop: picker.control.getBoundingClientRect().top,
                        hit: picker.dropdown.contains(document.elementFromPoint(content.left + 20, content.bottom - 10))};
                });
                assert.ok(geometry.top >= 0 && geometry.bottom <= 720, "menu must fit the viewport");
                assert.ok(geometry.left >= 0 && geometry.right <= width, "menu must fit the viewport width");
                if (width > 700) assert.ok(geometry.bottom <= geometry.controlTop, "bottom-row menu should open upwards");
                assert.ok(geometry.hit, "card/modal must not clip or cover the bottom options");
                await page.mouse.move(geometry.left + 20, geometry.top + 30);
                await page.mouse.wheel(0, 700);
                await page.waitForFunction(() => document.getElementById("action").tomselect.dropdown_content.scrollTop > 0);
                await page.screenshot({path: path.join(screenshots, `${width}-${theme}.png`)});
                await page.locator('#action-ts-dropdown [data-value="39"]').click();
                assert.equal(await page.locator("#action").inputValue(), "39");
                await page.locator("#modal .ts-control").click();
                await page.locator("#action-ts-control").fill("Action 12");
                await page.locator('#action-ts-dropdown [data-value="12"]').click();
                assert.equal(await page.locator("#action").inputValue(), "12");
                await page.locator("#modal .ts-control").click();
                await page.evaluate(() => { document.querySelector(".app-modal-body").scrollTop = 0; });
                await page.waitForFunction(() => !document.getElementById("action").tomselect.isOpen);
                // Rebuilding action rows must remove the old portaled menu and listeners.
                await page.evaluate(() => {
                    destroyTomSelectIfExists(document.getElementById("action"));
                    initSearchableSelect("#action");
                });
                assert.equal(await page.locator("#action-ts-dropdown").count(), 1);
                await page.locator("#modal .ts-control").click();
                await page.locator("#action-ts-control").fill("Action 7");
                await page.waitForFunction(() => document.getElementById("action").tomselect.activeOption?.dataset.value === "7");
                await page.locator("#action-ts-control").press("Enter");
                assert.equal(await page.locator("#action").inputValue(), "7");
                await page.locator("#modal .ts-control").click();
                await page.evaluate(() => { document.getElementById("modal").style.display = "none"; });
                assert.equal(await page.locator("#action-ts-dropdown").isVisible(), false, "menu cannot escape a closed modal");
                assert.deepEqual(errors, []);
                await page.close();
            }
        }
        console.log("Searchable select layout: desktop/mobile, light/dark, pointer/keyboard and cleanup passed");
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
