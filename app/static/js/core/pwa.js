let incidentRelayInstallPrompt = null;
let incidentRelayPwaRefreshing = false;
let incidentRelayPwaTransitionTimer = null;

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

function beginIncidentRelayPwaTransition() {
    if (!isIncidentRelayPwaStandalone()) {
        return;
    }

    if (incidentRelayPwaTransitionTimer) {
        clearTimeout(incidentRelayPwaTransitionTimer);
        incidentRelayPwaTransitionTimer = null;
    }

    document.documentElement.classList.add("incidentrelay-pwa-transition");
}

function finishIncidentRelayPwaTransition(delay) {
    if (incidentRelayPwaTransitionTimer) {
        clearTimeout(incidentRelayPwaTransitionTimer);
    }

    incidentRelayPwaTransitionTimer = setTimeout(function () {
        document.documentElement.classList.remove("incidentrelay-pwa-transition");
        incidentRelayPwaTransitionTimer = null;
    }, delay || 0);
}

function setupIncidentRelayPwaTransitionMask() {
    if (!isIncidentRelayPwaStandalone()) {
        document.documentElement.classList.remove("incidentrelay-pwa-transition");
        return;
    }

    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") {
            beginIncidentRelayPwaTransition();
            return;
        }

        finishIncidentRelayPwaTransition(300);
    });

    window.addEventListener("pagehide", beginIncidentRelayPwaTransition);
    window.addEventListener("pageshow", function () {
        finishIncidentRelayPwaTransition(300);
    });

    finishIncidentRelayPwaTransition(300);
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

    navigator.serviceWorker.addEventListener("message", function (event) {
        const data = event.data || {};
        const replyPort = event.ports && event.ports[0];

        if (data.type === "INCIDENTRELAY_PREPARE_NAVIGATION") {
            beginIncidentRelayPwaTransition();

            if (replyPort) {
                replyPort.postMessage({handled: true});
            }
            return;
        }

        if (data.type !== "INCIDENTRELAY_NAVIGATE") {
            return;
        }

        let targetUrl;

        try {
            targetUrl = new URL(data.url || "/alerts", window.location.origin);
        } catch (error) {
            if (replyPort) {
                replyPort.postMessage({handled: false});
            }
            return;
        }

        if (
            targetUrl.origin !== window.location.origin
            || typeof navigate !== "function"
        ) {
            if (replyPort) {
                replyPort.postMessage({handled: false});
            }
            return;
        }

        navigate(
            targetUrl.pathname + targetUrl.search + targetUrl.hash,
            true
        );
        finishIncidentRelayPwaTransition();

        if (replyPort) {
            replyPort.postMessage({handled: true});
        }
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
    setupIncidentRelayPwaTransitionMask();
    setupIncidentRelayPwaInstallPrompt();
    registerIncidentRelayServiceWorker();
});
