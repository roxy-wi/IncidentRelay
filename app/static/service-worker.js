const IR_PWA_VERSION = "incidentrelay-pwa-v1.0.8";
const IR_STATIC_CACHE = IR_PWA_VERSION + "-static";
const IR_OFFLINE_CACHE = IR_PWA_VERSION + "-offline";
const OFFLINE_URL = "/static/offline.html";

const PRECACHE_URLS = [
    OFFLINE_URL,
    "/manifest.webmanifest",
    "/static/images/pwa/icon-192.png",
    "/static/images/pwa/icon-512.png",
    "/static/images/pwa/maskable-192.png",
    "/static/images/pwa/maskable-512.png",
    "/static/images/pwa/apple-touch-icon.png",
    "/static/images/pwa/screenshots/desktop-alerts.png",
    "/static/images/pwa/screenshots/mobile-alerts.png"
];

const STATIC_CACHE_LIMIT = 120;

function isSameOrigin(url) {
    return url.origin === self.location.origin;
}

function isApiRequest(url) {
    return (
        url.pathname.startsWith("/api/")
        || url.pathname.startsWith("/integrations/")
        || url.pathname.startsWith("/auth/")
    );
}

function isStaticAsset(url) {
    return (
        url.pathname.startsWith("/static/")
        || url.pathname === "/manifest.webmanifest"
    );
}

function isCacheableStaticResponse(response) {
    return response && response.ok && response.status === 200;
}

async function trimCache(cacheName, maxEntries) {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();

    if (keys.length <= maxEntries) {
        return;
    }

    await cache.delete(keys[0]);
    return trimCache(cacheName, maxEntries);
}

async function staleWhileRevalidateStatic(request) {
    const cache = await caches.open(IR_STATIC_CACHE);
    const cached = await cache.match(request);

    const networkPromise = fetch(request)
        .then(function (response) {
            if (isCacheableStaticResponse(response)) {
                cache.put(request, response.clone());
                trimCache(IR_STATIC_CACHE, STATIC_CACHE_LIMIT);
            }

            return response;
        })
        .catch(function () {
            return cached;
        });

    return cached || networkPromise;
}

async function networkOnlyWithOfflineFallback(request) {
    try {
        return await fetch(request);
    } catch (error) {
        const cache = await caches.open(IR_OFFLINE_CACHE);
        const offline = await cache.match(OFFLINE_URL);

        if (offline) {
            return offline;
        }

        throw error;
    }
}

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(IR_OFFLINE_CACHE)
            .then(function (cache) {
                return cache.addAll(PRECACHE_URLS);
            })
            .then(function () {
                return self.skipWaiting();
            })
    );
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys()
            .then(function (cacheNames) {
                return Promise.all(
                    cacheNames
                        .filter(function (cacheName) {
                            return (
                                cacheName.startsWith("incidentrelay-pwa-")
                                && cacheName.indexOf(IR_PWA_VERSION) !== 0
                            );
                        })
                        .map(function (cacheName) {
                            return caches.delete(cacheName);
                        })
                );
            })
            .then(function () {
                return self.clients.claim();
            })
    );
});

const IR_LOCALE_CACHE = "incidentrelay-settings";
const IR_LOCALE_REQUEST = "/__incidentrelay_locale__";
const IR_SW_MESSAGES = {
    en: {
        acknowledge: "Acknowledge",
        resolve: "Resolve",
        shelve: "Shelve 1h",
        unshelve: "Unshelve",
        alert: "Alert",
        action_failed: "Action failed: {error}",
        unknown_error: "unknown error",
        network_error: "network error",
        acknowledged: "{alert} acknowledged",
        resolved: "{alert} resolved",
        shelved: "{alert} shelved for 1 hour",
        unshelved: "{alert} unshelved"
    },
    ru: {
        acknowledge: "Подтвердить",
        resolve: "Закрыть",
        shelve: "Отложить на 1 ч",
        unshelve: "Вернуть",
        alert: "Алерт",
        action_failed: "Не удалось выполнить действие: {error}",
        unknown_error: "неизвестная ошибка",
        network_error: "ошибка сети",
        acknowledged: "{alert} подтверждён",
        resolved: "{alert} закрыт",
        shelved: "{alert} отложен на 1 час",
        unshelved: "{alert} возвращён"
    },
    de: {
        acknowledge: "Bestätigen",
        resolve: "Lösen",
        shelve: "1 Std. zurückstellen",
        unshelve: "Zurückholen",
        alert: "Alarm",
        action_failed: "Aktion fehlgeschlagen: {error}",
        unknown_error: "unbekannter Fehler",
        network_error: "Netzwerkfehler",
        acknowledged: "{alert} bestätigt",
        resolved: "{alert} gelöst",
        shelved: "{alert} für 1 Stunde zurückgestellt",
        unshelved: "{alert} wieder aktiviert"
    },
    fr: {
        acknowledge: "Acquitter",
        resolve: "Résoudre",
        shelve: "Reporter 1 h",
        unshelve: "Réactiver",
        alert: "Alerte",
        action_failed: "Échec de l’action : {error}",
        unknown_error: "erreur inconnue",
        network_error: "erreur réseau",
        acknowledged: "{alert} acquittée",
        resolved: "{alert} résolue",
        shelved: "{alert} reportée pendant 1 heure",
        unshelved: "{alert} réactivée"
    },
    es: {
        acknowledge: "Reconocer",
        resolve: "Resolver",
        shelve: "Posponer 1 h",
        unshelve: "Reactivar",
        alert: "Alerta",
        action_failed: "La acción falló: {error}",
        unknown_error: "error desconocido",
        network_error: "error de red",
        acknowledged: "{alert} reconocida",
        resolved: "{alert} resuelta",
        shelved: "{alert} pospuesta durante 1 hora",
        unshelved: "{alert} reactivada"
    },
    zh: {
        acknowledge: "确认",
        resolve: "解决",
        shelve: "搁置 1 小时",
        unshelve: "取消搁置",
        alert: "告警",
        action_failed: "操作失败：{error}",
        unknown_error: "未知错误",
        network_error: "网络错误",
        acknowledged: "已确认 {alert}",
        resolved: "已解决 {alert}",
        shelved: "已搁置 {alert} 1 小时",
        unshelved: "已取消搁置 {alert}"
    }
};

function normalizeIncidentRelayLocale(value) {
    const locale = String(value || "")
        .toLowerCase()
        .replace("_", "-");

    if (locale.startsWith("ru")) {
        return "ru";
    }
    if (locale.startsWith("de")) {
        return "de";
    }
    if (locale.startsWith("fr")) {
        return "fr";
    }
    if (locale.startsWith("es")) {
        return "es";
    }
    if (locale.startsWith("zh")) {
        return "zh";
    }
    return "en";
}

function incidentRelaySwText(locale, key, params) {
    const selectedLocale = normalizeIncidentRelayLocale(locale);
    const template = (
        IR_SW_MESSAGES[selectedLocale][key]
        || IR_SW_MESSAGES.en[key]
        || key
    );
    const replacements = params || {};

    return template.replace(/\{([A-Za-z0-9_]+)\}/g, function (match, name) {
        return Object.prototype.hasOwnProperty.call(replacements, name)
            ? String(replacements[name])
            : match;
    });
}

async function saveIncidentRelayLocale(locale) {
    const selectedLocale = normalizeIncidentRelayLocale(locale);
    const cache = await caches.open(IR_LOCALE_CACHE);

    await cache.put(
        IR_LOCALE_REQUEST,
        new Response(selectedLocale, {
            headers: {"Content-Type": "text/plain; charset=utf-8"}
        })
    );

    return selectedLocale;
}

async function loadIncidentRelayLocale(preferredLocale) {
    if (preferredLocale) {
        return saveIncidentRelayLocale(preferredLocale);
    }

    try {
        const cache = await caches.open(IR_LOCALE_CACHE);
        const response = await cache.match(IR_LOCALE_REQUEST);

        if (response) {
            return normalizeIncidentRelayLocale(await response.text());
        }
    } catch (error) {
        // Browser language is a safe fallback when Cache Storage is unavailable.
    }

    return normalizeIncidentRelayLocale(
        self.navigator && self.navigator.language
    );
}

self.addEventListener("message", function (event) {
    if (!event.data) {
        return;
    }

    if (event.data.type === "SKIP_WAITING") {
        self.skipWaiting();
        return;
    }

    if (event.data.type === "SET_LOCALE") {
        event.waitUntil(saveIncidentRelayLocale(event.data.locale));
    }
});

self.addEventListener("fetch", function (event) {
    const request = event.request;

    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);

    if (!isSameOrigin(url)) {
        return;
    }

    if (isApiRequest(url)) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(networkOnlyWithOfflineFallback(request));
        return;
    }

    if (isStaticAsset(url)) {
        event.respondWith(staleWhileRevalidateStatic(request));
    }
});

self.addEventListener("push", function (event) {
    event.waitUntil((async function () {
        let payload = {};

        if (event.data) {
            try {
                payload = event.data.json();
            } catch (error) {
                payload = {
                    title: "IncidentRelay",
                    body: event.data.text()
                };
            }
        }

        const locale = await loadIncidentRelayLocale(payload.locale);
        const title = payload.title || "IncidentRelay";
        const actionTokens = payload.action_tokens || {};
        const actions = [];

        if (actionTokens.ack) {
            actions.push({
                action: "ack",
                title: incidentRelaySwText(locale, "acknowledge")
            });
        }

        if (actionTokens.resolve) {
            actions.push({
                action: "resolve",
                title: incidentRelaySwText(locale, "resolve")
            });
        }

        if (actionTokens.shelve) {
            actions.push({
                action: "shelve",
                title: incidentRelaySwText(locale, "shelve")
            });
        }

        if (actionTokens.unshelve) {
            actions.push({
                action: "unshelve",
                title: incidentRelaySwText(locale, "unshelve")
            });
        }

        const options = {
            body: payload.body || "",
            tag: payload.tag || `incidentrelay-${Date.now()}`,
            renotify: payload.renotify !== false,
            requireInteraction: payload.require_interaction !== false,
            silent: payload.silent === true,
            data: {
                url: payload.url || "/alerts",
                alert_id: payload.alert_id,
                alert_title: (
                    payload.alert_title
                    || payload.title
                    || incidentRelaySwText(locale, "alert")
                ),
                status: payload.status,
                action_tokens: actionTokens,
                locale
            },
            actions
        };

        if (!options.silent && Array.isArray(payload.vibrate)) {
            options.vibrate = payload.vibrate;
        }

        return self.registration.showNotification(title, options);
    })());
});

function requestClientMessage(client, type, targetUrl) {
    return new Promise(function (resolve) {
        const channel = new MessageChannel();
        let settled = false;

        const finish = function (handled) {
            if (settled) {
                return;
            }

            settled = true;
            resolve(handled);
        };

        const timeout = setTimeout(function () {
            finish(false);
        }, 500);

        channel.port1.onmessage = function (event) {
            clearTimeout(timeout);
            finish(Boolean(event.data && event.data.handled));
        };

        try {
            client.postMessage(
                {
                    type,
                    url: targetUrl
                },
                [channel.port2]
            );
        } catch (error) {
            clearTimeout(timeout);
            finish(false);
        }
    });
}

function requestClientNavigation(client, targetUrl) {
    return requestClientMessage(
        client,
        "INCIDENTRELAY_NAVIGATE",
        targetUrl
    );
}

function prepareClientNavigation(client, targetUrl) {
    return requestClientMessage(
        client,
        "INCIDENTRELAY_PREPARE_NAVIGATION",
        targetUrl
    );
}

function openIncidentRelayUrl(url) {
    const targetUrl = new URL(url || "/alerts", self.location.origin).href;

    return clients.matchAll({
        type: "window",
        includeUncontrolled: true
    }).then(async function (clientList) {
        for (const client of clientList) {
            const canUseRunningApp = (
                client.focused === true
                || client.visibilityState === "visible"
            );

            if (
                canUseRunningApp
                && "postMessage" in client
                && await requestClientNavigation(client, targetUrl)
            ) {
                if ("focus" in client) {
                    return client.focus();
                }

                return client;
            }

            if (!("navigate" in client)) {
                continue;
            }

            try {
                if ("postMessage" in client) {
                    await prepareClientNavigation(client, targetUrl);
                }

                const navigatedClient = await client.navigate(targetUrl);
                const focusedClient = navigatedClient || client;

                if ("focus" in focusedClient) {
                    return focusedClient.focus();
                }

                return focusedClient;
            } catch (error) {
                // Try opening a new window below when an existing client cannot navigate.
            }
        }

        if (clients.openWindow) {
            return clients.openWindow(targetUrl);
        }

        return null;
    });
}

self.addEventListener("notificationclick", function (event) {
    const notification = event.notification;
    const action = event.action || "open";
    const data = notification.data || {};
    const actionTokens = data.action_tokens || {};
    const url = data.url || "/alerts";

    notification.close();

    if (!["ack", "resolve", "shelve", "unshelve"].includes(action)) {
        event.waitUntil(openIncidentRelayUrl(url));
        return;
    }

    const token = actionTokens[action];

    if (!token) {
        event.waitUntil(openIncidentRelayUrl(url));
        return;
    }

    event.waitUntil((async function () {
        const locale = await loadIncidentRelayLocale(data.locale);

        try {
            const response = await fetch("/api/push/actions", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                credentials: "include",
                body: JSON.stringify({
                    action,
                    token
                })
            });
            const result = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || result.ok === false) {
                return self.registration.showNotification("IncidentRelay", {
                    body: incidentRelaySwText(
                        locale,
                        "action_failed",
                        {
                            error: (
                                result.error
                                || incidentRelaySwText(locale, "unknown_error")
                            )
                        }
                    ),
                    tag: `incidentrelay-action-error-${Date.now()}`,
                    data: {url, locale}
                });
            }

            const alertTitle = (
                data.alert_title
                || `${incidentRelaySwText(locale, "alert")} #${result.alert_id || data.alert_id || ""}`.trim()
            );
            const messageKey = {
                ack: "acknowledged",
                resolve: "resolved",
                shelve: "shelved",
                unshelve: "unshelved"
            }[action] || "resolved";
            const body = incidentRelaySwText(
                locale,
                messageKey,
                {alert: alertTitle}
            );

            const followUpTokens = result.action_tokens || {};
            const followUpActions = [];
            if (followUpTokens.unshelve) {
                followUpActions.push({
                    action: "unshelve",
                    title: incidentRelaySwText(locale, "unshelve")
                });
            }
            if (followUpTokens.resolve) {
                followUpActions.push({
                    action: "resolve",
                    title: incidentRelaySwText(locale, "resolve")
                });
            }

            return self.registration.showNotification("IncidentRelay", {
                body,
                tag: `incidentrelay-alert-${result.alert_id || data.alert_id || Date.now()}`,
                renotify: true,
                silent: false,
                actions: followUpActions,
                data: {
                    url,
                    locale,
                    alert_id: result.alert_id || data.alert_id,
                    alert_title: alertTitle,
                    action_tokens: followUpTokens
                }
            });
        } catch (error) {
            return self.registration.showNotification("IncidentRelay", {
                body: incidentRelaySwText(
                    locale,
                    "action_failed",
                    {error: incidentRelaySwText(locale, "network_error")}
                ),
                tag: `incidentrelay-action-error-${Date.now()}`,
                data: {url, locale}
            });
        }
    })());
});
