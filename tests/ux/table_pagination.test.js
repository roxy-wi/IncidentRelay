"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const handlers = new Map();
const context = {
    document: {},
    $: element => element === context.document ? {
        on: (event, selector, handler) => handlers.set(event + " " + selector, handler),
    } : {val: () => element.value},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("app/static/js/core/table_pagination.js", "utf8"), context);
let rendered;
let visible;
let changes = 0;
let items = Array.from({length: 53}, (_, index) => index + 1);
context.renderTablePaginationControls = options => { rendered = options.pagination; };
const pager = context.createClientTablePagination({
    id: "test-pagination", pageSize: 25,
    onChange: () => { changes++; visible = pager.render(items); },
});
function trigger(event, control, value) {
    handlers.get(event + " #test-pagination-" + control).call({value});
}
visible = pager.render(items);
assert.deepEqual(Array.from(visible), items.slice(0, 25));
assert.equal(rendered.from, 1);
assert.equal(rendered.to, 25);
assert.equal(rendered.total_pages, 3);
trigger("click", "prev-page");
assert.equal(changes, 0, "first page cannot go backwards");
trigger("click", "next-page");
assert.deepEqual(Array.from(visible), items.slice(25, 50));
trigger("click", "next-page");
assert.deepEqual(Array.from(visible), [51, 52, 53]);
assert.equal(rendered.has_next, false);
trigger("click", "next-page");
assert.equal(changes, 2, "last page cannot advance");
items = items.slice(0, 26);
visible = pager.render(items);
assert.deepEqual(Array.from(visible), [26], "deletion clamps to the new last page");
trigger("change", "page-size", "10");
assert.equal(rendered.page, 1);
assert.equal(visible.length, 10);
trigger("change", "page-size", "0");
assert.equal(rendered.page_size, 10, "reject invalid page sizes");
trigger("click", "next-page");
pager.reset();
visible = pager.render(items.slice(12, 13));
assert.deepEqual(Array.from(visible), [13], "filtering starts from the first page");
visible = pager.render([]);
assert.equal(visible.length, 0);
assert.equal(rendered.from, 0);
assert.equal(rendered.to, 0);
assert.equal(rendered.total_pages, 1);
assert.equal(rendered.has_prev, false);
assert.equal(rendered.has_next, false);
console.log("Client pagination boundaries, filtering and deletion passed");
