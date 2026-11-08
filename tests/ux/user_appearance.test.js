"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("app/static/js/core/user_appearance.js", "utf8") + "; this.appearance = UserAppearance;", sandbox);
const appearance = sandbox.appearance;
const vectors = JSON.parse(process.env.USER_COLOR_VECTORS);
for (const [id, color] of vectors) {
    assert.equal(appearance.color({id}), color);
    assert.equal(appearance.color({id: 999, user_id: id}), color);
}
assert.equal(appearance.color({id: 1, color: "#AB12EF"}), "#ab12ef");
assert.equal(appearance.color({id: 1, color: "red; background:url(x)"}), vectors[0][1]);
assert.equal(appearance.color({id: 1, color: "#abcdef\n"}), vectors[0][1]);
assert.equal(appearance.color(null), "#64748b");
assert.equal(appearance.name({user_display_name: "Alice", username: "admin"}), "Alice");
assert.equal(appearance.textColor("#ffffff"), "#000000");
assert.equal(appearance.textColor("#000000"), "#ffffff");

// The selected text color must meet WCAG AA contrast, even for middle shades.
function luminance(hex) {
    const values = hex.match(/[a-f0-9]{2}/gi).map(value => {
        const channel = parseInt(value, 16) / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
}
for (let id = 1; id <= 1000; id++) {
    const color = appearance.color({id});
    const light = luminance(color);
    const text = luminance(appearance.textColor(color));
    const contrast = (Math.max(light, text) + 0.05) / (Math.min(light, text) + 0.05);
    assert(contrast >= 4.5, color + " text contrast " + contrast);
}
console.log("User appearance color and contrast checks passed");
