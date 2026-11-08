"use strict";

const UserAppearance = {
    id(user) {
        return user ? Number(user.user_id || user.id || 0) : 0;
    },
    name(user) {
        return user && (user.display_name || user.user_display_name || user.username || user.email) || "?";
    },
    color(user) {
        if (user && typeof user.color === "string" && user.color.length === 7 && /^#[0-9a-f]{6}$/i.test(user.color)) {
            return user.color.toLowerCase();
        }
        const id = this.id(user);
        if (!id) { return "#64748b"; }
        // Same RGB permutation as app/user_colors.py; also supports older API data.
        return "#" + ((Math.imul(id, 0x9e3779) + 0x5c4b2d) & 0xffffff).toString(16).padStart(6, "0");
    },
    textColor(color) {
        const channels = [1, 3, 5].map(index => {
            const value = parseInt(color.slice(index, index + 2), 16) / 255;
            return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
        });
        const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
        return (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) ? "#000000" : "#ffffff";
    },
    paint(element, user) {
        const color = this.color(user);
        const target = $(element).attr("data-user-id", this.id(user) || "")
            .css({"background-color": color, color: this.textColor(color)});
        if (target.hasClass("calendar-assignment")) {
            target.css({"--calendar-user-color": color, "--calendar-user-bg": color});
        }
        return target;
    },
    avatar(user, className, label) {
        const name = label || this.name(user);
        const initial = Array.from(String(name).trim())[0] || "?";
        return this.paint($("<span>").addClass("user-avatar " + (className || ""))
            .attr("aria-hidden", "true").text(initial.toUpperCase()), user);
    },
    label(user, label) {
        const name = label || this.name(user);
        if (!user) { return $("<span>").text(name); }
        return $("<span>").addClass("user-identity")
            .append(this.avatar(user, "", this.name(user) === "?" ? name : this.name(user)))
            .append($("<span>").addClass("user-identity-name").text(name));
    },
    option(data) {
        const user = data.value ? {id: data.value, color: data.color, display_name: data.display_name} : null;
        return this.label(user, data.text)[0];
    },
    refresh(user) {
        const id = this.id(user);
        if (!id) { return; }
        const appearance = this;
        $(".user-avatar, .calendar-assignment").filter(function () {
            return Number($(this).attr("data-user-id")) === id;
        }).each(function () { appearance.paint(this, user); });
    }
};
