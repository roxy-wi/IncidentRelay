function initSidebar() {
    const storageKey = "incidentrelay_sidebar_collapsed";
    const sidebar = document.getElementById("app-sidebar");
    const toggle = document.getElementById("sidebar-toggle");

    if (!sidebar || !toggle) {
        return;
    }

    function setCollapsed(collapsed) {
        sidebar.classList.toggle("is-collapsed", collapsed);
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
        toggle.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");

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
