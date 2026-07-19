let incidentRelayInstallPrompt = null;
let incidentRelayPwaRefreshing = false;

function currentIncidentRelayLocale() {
    if (window.i18n && i18n.locale) {
        return i18n.locale;
    }

    return document.documentElement.lang || navigator.language || "en";
}

function syncIncidentRelayServiceWorkerLocale(registration) {
    if (!registration) {
        return;
    }

    const worker = registration.active || registration.waiting || registration.installing;

    if (worker) {
        worker.postMessage({
            type: "SET_LOCALE",
            locale: currentIncidentRelayLocale()
        });
    }
}

function isIncidentRelayPwaStandalone() {
    return (
        window.matchMedia("(display-mode: standalone)").matches
        || window.navigator.standalone === true
    );
}

function setPwaInstallButtonVisible(visible) {
    const button = $("#topbar-install-app");

    if (!button.length) {
        return;
    }

    button.toggleClass("is-hidden", !visible);
}

function installIncidentRelayPwa() {
    if (!incidentRelayInstallPrompt) {
        return;
    }

    incidentRelayInstallPrompt.prompt();

    incidentRelayInstallPrompt.userChoice.finally(function () {
        incidentRelayInstallPrompt = null;
        setPwaInstallButtonVisible(false);
    });
}

function registerIncidentRelayServiceWorker() {
    if (!("serviceWorker" in navigator)) {
        return;
    }

    navigator.serviceWorker.register("/service-worker.js", {
        scope: "/"
    }).then(function (registration) {
        syncIncidentRelayServiceWorkerLocale(registration);

        if (registration.waiting) {
            registration.waiting.postMessage({type: "SKIP_WAITING"});
        }

        registration.addEventListener("updatefound", function () {
            const worker = registration.installing;

            if (!worker) {
                return;
            }

            worker.addEventListener("statechange", function () {
                if (
                    worker.state === "installed"
                    && navigator.serviceWorker.controller
                ) {
                    worker.postMessage({type: "SKIP_WAITING"});
                }
            });
        });
    }).catch(function (error) {
        console.warn("IncidentRelay service worker registration failed", error);
    });

    navigator.serviceWorker.addEventListener("controllerchange", function () {
        if (incidentRelayPwaRefreshing) {
            return;
        }

        incidentRelayPwaRefreshing = true;

        navigator.serviceWorker.ready.then(function (registration) {
            syncIncidentRelayServiceWorkerLocale(registration);
        });

        window.location.reload();
    });
}

function setupIncidentRelayPwaInstallPrompt() {
    if (isIncidentRelayPwaStandalone()) {
        setPwaInstallButtonVisible(false);
        return;
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        incidentRelayInstallPrompt = event;
        setPwaInstallButtonVisible(true);
    });

    window.addEventListener("appinstalled", function () {
        incidentRelayInstallPrompt = null;
        setPwaInstallButtonVisible(false);
    });

    $(document).on("click", "#topbar-install-app", function () {
        installIncidentRelayPwa();
    });
}

$(document).ready(function () {
    setupIncidentRelayPwaInstallPrompt();
    registerIncidentRelayServiceWorker();
});
