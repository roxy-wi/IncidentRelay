/* Restore explicit collapsed/expanded sidebar sections after the sidebar bootstrap.
 * This is deliberately separate from sidebar.js for installations that customize it.
 */
(function () {
    "use strict";

    function restoreSidebarGroups() {
        const sidebar = document.getElementById("app-sidebar");
        if (!sidebar) {
            return;
        }

        const rawPath = window.location.pathname.replace(/\/+$/, "") || "/";
        const routePath = typeof normalizeAppRoutePath === "function"
            ? normalizeAppRoutePath(rawPath)
            : rawPath;

        sidebar.querySelectorAll(".menu-group[data-menu-group]").forEach(function (group) {
            const key = "incidentrelay_menu_group_" + group.dataset.menuGroup + "_expanded";
            let saved = null;
            try {
                saved = window.localStorage.getItem(key);
            } catch (error) {
                // Storage may be unavailable; the current page still remains usable.
            }

            const active = Array.from(group.querySelectorAll(".menu-link[href]"))
                .some(function (link) { return (link.getAttribute("href") || "") === routePath; });
            const isExpanded = saved === "0" ? false
                : saved === "1" ? true
                    : active || group.dataset.menuDefaultExpanded === "true";

            group.classList.toggle("is-active", active);
            group.classList.toggle("is-expanded", isExpanded);
            const toggle = group.querySelector(":scope > .menu-group-toggle");
            if (toggle) {
                toggle.setAttribute("aria-expanded", isExpanded ? "true" : "false");
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", restoreSidebarGroups);
    } else {
        restoreSidebarGroups();
    }
})();
