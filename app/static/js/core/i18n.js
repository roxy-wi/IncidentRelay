(function (window, document) {
    "use strict";

    const config = window.__INCIDENTRELAY_I18N__ || {};
    const messages = config.messages || {};
    const supportedLocales = config.supportedLocales || {};
    const locale = config.locale || "en";
    const COOKIE_NAME = "incidentrelay_locale";
    const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

    function interpolate(value, params) {
        const replacements = params || {};

        return String(value).replace(/\{([A-Za-z0-9_]+)\}/g, function (match, key) {
            if (!Object.prototype.hasOwnProperty.call(replacements, key)) {
                return match;
            }

            return String(replacements[key]);
        });
    }

    function t(key, params, fallback) {
        const hasMessage = Object.prototype.hasOwnProperty.call(messages, key);
        const value = hasMessage
            ? messages[key]
            : (fallback === undefined ? key : fallback);

        return interpolate(value, params);
    }

    function setLocale(nextLocale) {
        if (!Object.prototype.hasOwnProperty.call(supportedLocales, nextLocale)) {
            return false;
        }

        document.cookie = [
            COOKIE_NAME + "=" + encodeURIComponent(nextLocale),
            "Path=/",
            "Max-Age=" + COOKIE_MAX_AGE,
            "SameSite=Lax",
        ].join("; ");

        window.location.reload();
        return true;
    }

    function bindLocaleSelectors(root) {
        const scope = root || document;

        scope.querySelectorAll("[data-locale-select]").forEach(function (select) {
            select.value = locale;

            if (select.dataset.localeBound === "true") {
                return;
            }

            select.dataset.localeBound = "true";
            select.addEventListener("change", function () {
                setLocale(select.value);
            });
        });
    }

    function setText(selector, key) {
        const element = document.querySelector(selector);
        if (element) {
            element.textContent = t(key, {}, element.textContent.trim());
        }
    }

    function setAttribute(selector, attribute, key) {
        const element = document.querySelector(selector);
        if (element) {
            element.setAttribute(
                attribute,
                t(key, {}, element.getAttribute(attribute) || "")
            );
        }
    }

    function translateMenu() {
        const pageKeys = {
            "dashboard": "nav.overview",
            "alerts": "nav.alerts",
            "rotations": "nav.rotations",
            "calendar": "nav.calendar",
            "routes": "nav.routes",
            "heartbeats": "nav.heartbeats",
            "services": "nav.service_catalog",
            "business-services": "nav.business_services",
            "maintenance-windows": "nav.maintenance",
            "notification-policies": "nav.notification_policies",
            "matcher-presets": "nav.matcher_presets",
            "priority-policies": "nav.priority_policies",
            "escalation-policies": "nav.escalation_policies",
            "channels": "nav.channels",
            "silences": "nav.silences",
            "teams": "nav.teams",
            "groups": "nav.groups",
            "admin-users": "nav.users",
            "sso": "nav.sso",
        };

        Object.keys(pageKeys).forEach(function (page) {
            const link = document.querySelector(
                '.menu-link[data-page="' + page + '"]'
            );

            if (!link) {
                return;
            }

            const key = pageKeys[page];
            const text = link.querySelector(".menu-text");
            const fallback = text ? text.textContent.trim() : link.title;
            const translated = t(key, {}, fallback);

            if (text) {
                text.textContent = translated;
            }

            link.title = translated;
        });

        setText("#services-menu-toggle .menu-text", "nav.services");
        setAttribute("#services-menu-toggle", "title", "nav.services");
        setText(".menu-section-title", "nav.administration");
        setText('a.menu-link[href="/docs"] .menu-text', "nav.swagger");
        setAttribute('a.menu-link[href="/docs"]', "title", "nav.swagger");
    }

    function translateShell() {
        document.documentElement.lang = locale;
        translateMenu();

        setText('label[for="global-language-filter"]', "common.language");
        setText('label[for="global-team-filter"]', "common.team");
        setText("#app-dialog-title", "common.message");
        setText("#app-dialog-cancel", "common.cancel");
        setText("#app-dialog-confirm", "common.ok");

        setAttribute("#sidebar-toggle", "aria-label", "common.collapse_sidebar");
        setAttribute(
            "#topbar-oncall-indicator",
            "title",
            "common.loading_oncall_status"
        );
        setAttribute(
            "#topbar-oncall-indicator",
            "aria-label",
            "common.loading_oncall_status"
        );
        setAttribute("#topbar-logout", "title", "common.logout");
        setAttribute("#topbar-logout", "aria-label", "common.logout");
        setAttribute("#topbar-install-app", "title", "common.install_app");
        setAttribute("#topbar-install-app", "aria-label", "common.install_app");
        setAttribute("#app-dialog-close", "aria-label", "common.close");
    }

    function translateLogin() {
        if (!document.querySelector(".login-page")) {
            return;
        }

        document.title = "IncidentRelay - " + t("login.title", {}, "Login");
        setText(".login-badge", "login.badge");
        setText(".login-form-wrap > h1", "login.heading");
        setText(".login-description", "login.description");
        setText('label[for="login-language-select"]', "common.language");
        setText('label[for="username"]', "login.username");
        setAttribute("#username", "placeholder", "login.username_placeholder");
        setText('label[for="password"]', "login.password");
        setAttribute("#password", "placeholder", "login.password_placeholder");
        setText(".btn-login", "login.submit");
        setText(".login-divider span", "login.sso");
    }

    function initialize() {
        bindLocaleSelectors(document);
        translateShell();
        translateLogin();
    }

    window.i18n = Object.freeze({
        locale: locale,
        supportedLocales: supportedLocales,
        t: t,
        setLocale: setLocale,
        bindLocaleSelectors: bindLocaleSelectors,
        translateShell: translateShell,
        translateLogin: translateLogin,
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})(window, document);
