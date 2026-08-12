(function (window, document) {
    "use strict";

    const config = window.__INCIDENTRELAY_UI__ || {};
    const supportedThemes = ["system", "light", "dark"];
    const mediaQuery = window.matchMedia
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;
    let preference = normalizeTheme(config.theme) || "system";

    function normalizeTheme(value) {
        const normalized = String(value || "").trim().toLowerCase();
        return supportedThemes.indexOf(normalized) >= 0 ? normalized : null;
    }

    function resolveColorScheme(value) {
        const normalized = normalizeTheme(value) || "system";

        if (normalized === "dark") {
            return "dark";
        }

        if (normalized === "light") {
            return "light";
        }

        return mediaQuery && mediaQuery.matches ? "dark" : "light";
    }

    function updateThemeColor(colorScheme) {
        const element = document.querySelector('meta[name="theme-color"]');
        if (element) {
            element.setAttribute(
                "content",
                colorScheme === "dark" ? "#0f172a" : "#0b5cff"
            );
        }
    }

    function applyChartDefaults(colorScheme) {
        if (!window.Chart || !window.Chart.defaults) {
            return;
        }

        const dark = colorScheme === "dark";
        window.Chart.defaults.color = dark ? "#cbd5e1" : "#334155";
        window.Chart.defaults.borderColor = dark
            ? "rgba(148, 163, 184, 0.22)"
            : "rgba(100, 116, 139, 0.18)";
    }

    function applyTheme(nextPreference) {
        preference = normalizeTheme(nextPreference) || "system";
        const colorScheme = resolveColorScheme(preference);

        document.documentElement.dataset.theme = preference;
        document.documentElement.dataset.colorScheme = colorScheme;
        document.documentElement.style.colorScheme = colorScheme;
        updateThemeColor(colorScheme);
        applyChartDefaults(colorScheme);

        document.dispatchEvent(
            new CustomEvent("incidentrelay:theme-change", {
                detail: {
                    preference: preference,
                    colorScheme: colorScheme,
                },
            })
        );

        return colorScheme;
    }

    function handleSystemThemeChange() {
        if (preference === "system") {
            applyTheme(preference);
        }
    }

    if (mediaQuery) {
        if (typeof mediaQuery.addEventListener === "function") {
            mediaQuery.addEventListener("change", handleSystemThemeChange);
        } else if (typeof mediaQuery.addListener === "function") {
            mediaQuery.addListener(handleSystemThemeChange);
        }
    }

    window.AppTheme = Object.freeze({
        apply: applyTheme,
        applyChartDefaults: function () {
            applyChartDefaults(resolveColorScheme(preference));
        },
        getPreference: function () {
            return preference;
        },
        getColorScheme: function () {
            return resolveColorScheme(preference);
        },
        normalize: normalizeTheme,
        supportedThemes: supportedThemes.slice(),
    });

    applyTheme(preference);
})(window, document);
