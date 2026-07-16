function normalizeSidebarPath(path) {
    const normalized = String(path || "/").replace(/\/+$/, "");
    return normalized || "/";
}

function setSidebarMenuGroupExpanded(group, expanded, persist) {
    const toggle = group.querySelector(".menu-group-toggle");

    group.classList.toggle("is-expanded", expanded);

    if (toggle) {
        toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    }

    if (persist === false) {
        return;
    }

    const groupName = group.dataset.menuGroup;

    if (groupName) {
        localStorage.setItem(
            "incidentrelay_menu_group_" + groupName + "_expanded",
            expanded ? "1" : "0"
        );
    }
}

function initSidebar() {
    const storageKey = "incidentrelay_sidebar_collapsed";
    const sidebar = document.getElementById("app-sidebar");
    const toggle = document.getElementById("sidebar-toggle");

    if (!sidebar || !toggle) {
        return;
    }

    function setCollapsed(collapsed) {
        sidebar.classList.toggle("is-collapsed", collapsed);

        toggle.setAttribute(
            "aria-expanded",
            collapsed ? "false" : "true"
        );
        const toggleLabel = collapsed
            ? i18n.t("common.expand_sidebar", {}, "Expand sidebar")
            : i18n.t("common.collapse_sidebar", {}, "Collapse sidebar");

        toggle.setAttribute("aria-label", toggleLabel);
        toggle.setAttribute("title", toggleLabel);

        const icon = toggle.querySelector(".sidebar-toggle-icon");

        if (icon) {
            icon.textContent = collapsed ? "›" : "‹";
        }

        localStorage.setItem(storageKey, collapsed ? "1" : "0");
    }

    setCollapsed(localStorage.getItem(storageKey) === "1");

    toggle.addEventListener("click", function () {
        setCollapsed(!sidebar.classList.contains("is-collapsed"));
    });

    const currentPath = normalizeSidebarPath(window.location.pathname);

    sidebar.querySelectorAll(".menu-group").forEach(function (group) {
        const groupName = group.dataset.menuGroup;
        const groupToggle = group.querySelector(".menu-group-toggle");

        if (!groupToggle) {
            return;
        }

        const containsCurrentPath = Array.from(
            group.querySelectorAll(".menu-link[href]")
        ).some(function (link) {
            return normalizeSidebarPath(link.getAttribute("href"))
                === currentPath;
        });

        if (containsCurrentPath) {
            group.classList.add("is-active");
        }

        const storedValue = groupName
            ? localStorage.getItem(
                "incidentrelay_menu_group_"
                + groupName
                + "_expanded"
            )
            : null;

        setSidebarMenuGroupExpanded(
            group,
            containsCurrentPath || storedValue === "1",
            false
        );

        groupToggle.addEventListener("click", function () {
            if (sidebar.classList.contains("is-collapsed")) {
                setCollapsed(false);
                setSidebarMenuGroupExpanded(group, true);
                return;
            }

            setSidebarMenuGroupExpanded(
                group,
                !group.classList.contains("is-expanded")
            );
        });
    });

    document.querySelectorAll(".brand-link[data-page]").forEach(function (link) {
        link.addEventListener("click", function (event) {
            event.preventDefault();

            if (typeof navigate === "function") {
                navigate("/", true);
                return;
            }

            window.location.href = "/";
        });
    });
}

document.addEventListener("DOMContentLoaded", initSidebar);
