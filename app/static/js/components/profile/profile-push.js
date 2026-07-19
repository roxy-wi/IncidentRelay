(function () {
    const PUSH_CONFIG_URL = "/api/profile/push/vapid-public-key";
    const PUSH_SUBSCRIPTIONS_URL = "/api/profile/push/subscriptions";
    const PUSH_TEST_URL = "/api/profile/push/test";
    const SERVICE_WORKER_URL = "/service-worker.js";

    document.addEventListener("DOMContentLoaded", () => {
        const card = document.getElementById("browser-push-card");

        if (!card) {
            return;
        }

        bindPushProfileEvents();
        loadPushDevices();
    });

    function bindPushProfileEvents() {
        const enableBtn = document.getElementById("enable-push-btn");
        const testBtn = document.getElementById("send-test-push-btn");
        const reloadBtn = document.getElementById("reload-push-devices-btn");

        if (enableBtn) {
            enableBtn.addEventListener("click", async () => {
                await runWithButtonState(enableBtn, i18n.t("profile.push.enabling"), enablePushOnCurrentDevice);
            });
        }

        if (testBtn) {
            testBtn.addEventListener("click", async () => {
                await runWithButtonState(testBtn, i18n.t("profile.push.sending"), sendTestPush);
            });
        }

        if (reloadBtn) {
            reloadBtn.addEventListener("click", async () => {
                await runWithButtonState(reloadBtn, i18n.t("profile.push.reloading"), loadPushDevices);
            });
        }
    }

    async function runWithButtonState(button, loadingText, callback) {
        const originalText = button.textContent;

        button.disabled = true;
        button.textContent = loadingText;

        try {
            await callback();
        } catch (error) {
            showPushStatus(error.message || i18n.t("profile.push.action_failed"), "error");
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    async function enablePushOnCurrentDevice() {
        ensurePushSupported();

        const config = await getPushConfig();

        if (!config.enabled || !config.public_key) {
            throw new Error(i18n.t("profile.push.not_configured"));
        }

        const permission = await Notification.requestPermission();

        if (permission !== "granted") {
            throw new Error(i18n.t("profile.push.permission_denied"));
        }

        const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL);
        await navigator.serviceWorker.ready;

        let subscription = await registration.pushManager.getSubscription();

        if (!subscription) {
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(config.public_key)
            });
        }

        const payload = subscription.toJSON();
        payload.device_name = getDeviceName();

        const response = await fetch(PUSH_SUBSCRIPTIONS_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const error = await readJsonSafe(response);
            throw new Error(error.message || error.error || i18n.t("profile.push.save_failed"));
        }

        showPushStatus(i18n.t("profile.push.enabled_status"), "success");
        await loadPushDevices();
    }

    async function sendTestPush() {
        const response = await fetch(PUSH_TEST_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            }
        });

        if (!response.ok) {
            const error = await readJsonSafe(response);
            throw new Error(error.message || error.error || i18n.t("profile.push.test_failed"));
        }

        const result = await response.json();

        if (!result.sent) {
            showPushStatus(i18n.t("profile.push.no_devices"), "warning");
            return;
        }

        showPushStatus(i18n.t("profile.push.test_sent", {count: result.sent}), "success");
    }

    async function loadPushDevices() {
        const tbody = document.getElementById("push-devices-body");

        if (!tbody) {
            return;
        }

        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="muted">${i18n.t("profile.push.loading")}</td>
            </tr>
        `;

        const response = await fetch(PUSH_SUBSCRIPTIONS_URL);

        if (!response.ok) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-danger">${i18n.t("profile.push.load_failed")}</td>
                </tr>
            `;
            return;
        }

        const devices = await response.json();

        if (!devices.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="muted">${i18n.t("profile.push.no_devices_yet")}</td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = devices.map(device => renderPushDeviceRow(device)).join("");

        tbody.querySelectorAll("[data-disable-push-id]").forEach(button => {
            button.addEventListener("click", async () => {
                const subscriptionId = button.getAttribute("data-disable-push-id");

                await runWithButtonState(button, i18n.t("profile.push.disabling"), async () => {
                    await disablePushDevice(subscriptionId);
                });
            });
        });
    }

    function renderPushDeviceRow(device) {
        const status = device.enabled
            ? `<span class="badge badge-success">${i18n.t("profile.common.enabled")}</span>`
            : `<span class="badge badge-muted">${i18n.t("profile.common.disabled")}</span>`;

        const deviceName = escapeHtml(device.device_name || detectDeviceFromUserAgent(device.user_agent) || i18n.t("profile.push.browser"));
        const userAgent = device.user_agent ? `<div class="muted small">${escapeHtml(device.user_agent)}</div>` : "";

        return `
            <tr>
                <td>
                    <strong>${deviceName}</strong>
                    ${userAgent}
                </td>
                <td>${status}</td>
                <td>${formatDateTime(device.last_seen_at)}</td>
                <td>${formatDateTime(device.created_at)}</td>
                <td class="text-right">
                    <button
                        type="button"
                        class="btn btn-sm btn-danger"
                        data-disable-push-id="${device.id}"
                    >
                        ${i18n.t("profile.actions.disable")}
                    </button>
                </td>
            </tr>
        `;
    }

    async function disablePushDevice(subscriptionId) {
        const response = await fetch(`${PUSH_SUBSCRIPTIONS_URL}/${subscriptionId}`, {
            method: "DELETE"
        });

        if (!response.ok) {
            const error = await readJsonSafe(response);
            throw new Error(error.message || error.error || i18n.t("profile.push.disable_failed"));
        }

        showPushStatus(i18n.t("profile.push.disabled_status"), "success");
        await loadPushDevices();
    }

    async function getPushConfig() {
        const response = await fetch(PUSH_CONFIG_URL);

        if (!response.ok) {
            throw new Error(i18n.t("profile.push.config_failed"));
        }

        return response.json();
    }

    function ensurePushSupported() {
        if (!("serviceWorker" in navigator)) {
            throw new Error(i18n.t("profile.push.no_service_worker"));
        }

        if (!("PushManager" in window)) {
            throw new Error(i18n.t("profile.push.no_push"));
        }

        if (!("Notification" in window)) {
            throw new Error(i18n.t("profile.push.no_notifications"));
        }
    }

    function getDeviceName() {
        const input = document.getElementById("push-device-name");
        const value = input ? input.value.trim() : "";

        if (value) {
            return value;
        }

        return detectDeviceFromUserAgent(navigator.userAgent) || i18n.t("profile.push.browser");
    }

    function detectDeviceFromUserAgent(userAgent) {
        const ua = userAgent || "";

        if (/iPhone/i.test(ua)) {
            return "iPhone";
        }

        if (/iPad/i.test(ua)) {
            return "iPad";
        }

        if (/Android/i.test(ua)) {
            return i18n.t("profile.push.android");
        }

        if (/Macintosh|Mac OS X/i.test(ua)) {
            return i18n.t("profile.push.mac");
        }

        if (/Windows/i.test(ua)) {
            return i18n.t("profile.push.windows");
        }

        if (/Linux/i.test(ua)) {
            return i18n.t("profile.push.linux");
        }

        return i18n.t("profile.push.browser");
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, "+")
            .replace(/_/g, "/");

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; i += 1) {
            outputArray[i] = rawData.charCodeAt(i);
        }

        return outputArray;
    }

    function showPushStatus(message, type) {
        const status = document.getElementById("push-status");

        if (!status) {
            return;
        }

        status.textContent = message;
        status.dataset.status = type || "info";
    }

    function getAlertClass(type) {
        if (type === "success") {
            return "alert-success";
        }

        if (type === "warning") {
            return "alert-warning";
        }

        if (type === "error") {
            return "alert-danger";
        }

        return "alert-info";
    }

    function formatDateTime(value) {
        if (!value) {
            return `<span class="muted">${i18n.t("profile.tokens.never")}</span>`;
        }

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return `<span class="muted">${escapeHtml(value)}</span>`;
        }

        return date.toLocaleString(undefined, {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false
        });
    }

    async function readJsonSafe(response) {
        try {
            return await response.json();
        } catch (error) {
            return {};
        }
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
})();
