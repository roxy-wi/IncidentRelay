function getAuthHeaders() {
    /*
     * Return Authorization header from local storage token.
     */
    const token = typeof getStoredToken === "function"
        ? getStoredToken()
        : localStorage.getItem("incidentrelay_jwt");

    if (!token) {
        return {};
    }

    return {
        "Authorization": "Bearer " + token
    };
}


function apiRequest(method, url, data, onSuccess, onError) {
    /*
     * Common API request wrapper.
     *
     * All API helpers must go through this function so errors are handled
     * consistently across pages.
     */
    const ajaxOptions = {
        url: url,
        method: method,
        headers: getAuthHeaders(),
        success: function (response) {
            if (typeof onSuccess === "function") {
                onSuccess(response);
            }
        },
        error: function (xhr) {
            if (typeof onError === "function") {
                onError(xhr);
                return;
            }

            showApiError(xhr);
        }
    };

    if (data !== undefined && data !== null) {
        ajaxOptions.contentType = "application/json";
        ajaxOptions.data = JSON.stringify(data);
    }

    $.ajax(ajaxOptions);
}


function apiGet(url, onSuccess, onError) {
    /*
     * Send GET request.
     */
    apiRequest("GET", url, null, onSuccess, onError);
}


function apiPost(url, data, onSuccess, onError) {
    /*
     * Send POST request.
     */
    apiRequest("POST", url, data || {}, onSuccess, onError);
}


function apiPut(url, data, onSuccess, onError) {
    /*
     * Send PUT request.
     */
    apiRequest("PUT", url, data || {}, onSuccess, onError);
}


function apiDelete(url, onSuccess, onError) {
    /*
     * Send DELETE request.
     */
    apiRequest("DELETE", url, null, onSuccess, onError);
}

function translateKnownApiMessage(message) {
    /*
     * Translate stable server messages while preserving unknown details and
     * machine-readable error codes.
     */
    if (message === undefined || message === null) {
        return message;
    }

    const text = String(message);
    const messageKeys = {
        "Authentication is required": "final.api.authentication_required",
        "Valid JWT token is required": "final.api.valid_jwt_required",
        "JWT or API token authentication is required": "final.api.jwt_or_api_required",
        "Access denied.": "final.api.access_denied",
        "Access to this group is denied": "final.api.group_access_denied",
        "Access to this team is denied": "final.api.team_access_denied",
        "Access to this team resource is denied": "final.api.team_resource_denied",
        "Access to this team on-call schedule is denied": "final.api.team_oncall_denied",
        "Admin role is required": "final.api.admin_required",
        "Group Admin role is required": "final.api.group_admin_required",
        "Team manager role is required for this team": "final.api.team_manager_required",
        "Team responder role is required for this team": "final.api.team_responder_required",
        "Group editor or group admin role is required for this group": "final.api.group_editor_required",
        "Group user admin role is required for this group": "final.api.group_user_admin_required",
        "Team manager or group editor role is required for this team": "final.api.team_or_group_editor_required",
        "Team manager or group admin role is required for this team": "final.api.team_or_group_admin_required",
        "Request body is required": "final.api.request_body_required",
        "Request body must be valid JSON": "final.api.valid_json_required",
        "Invalid request.": "final.api.invalid_request",
        "Request validation failed": "final.api.validation_failed",
        "Invalid value": "final.api.invalid_value",
        "Requested resource was not found.": "final.api.requested_not_found",
        "Resource was not found": "final.api.resource_not_found",
        "User not found.": "final.api.user_not_found",
        "Team not found.": "final.api.team_not_found",
        "Rotation not found.": "final.api.rotation_not_found",
        "Alert group not found.": "final.api.alert_group_not_found",
        "Maintenance window not found.": "final.api.maintenance_not_found",
        "Business service not found": "final.api.business_service_not_found",
        "Notification rule not found.": "final.api.notification_rule_not_found",
        "Calendar feed was not found.": "final.api.calendar_feed_not_found",
        "Old password is invalid": "final.api.old_password_invalid",
        "You cannot disable your own user account": "final.api.self_disable_denied",
        "You cannot remove your own user account.": "final.api.self_remove_denied",
        "Selected group was not found": "final.api.selected_group_not_found",
        "Selected group is inactive": "final.api.selected_group_inactive",
        "Internal Server Error": "final.api.internal_server_error",
        "Unexpected server error. Check JSON log by error_id.": "final.api.unexpected_server_error",
        "Database constraint violation": "final.api.database_constraint",
        "User with this username or unique field already exists": "final.api.user_conflict",
        "Channel with this name already exists in this team": "final.api.channel_conflict",
        "Channel name must be unique within a team": "final.api.channel_unique",
        "Channel test failed.": "final.api.channel_test_failed",
        "Manual incident target not found.": "final.api.manual_incident_target_not_found",
        "Missing API token scope": "final.api.missing_scope"
    };
    const key = messageKeys[text];

    return key ? i18n.t(key, {}, text) : text;
}

function getApiErrorMessage(xhr, fallbackMessage) {
    /*
     * Extract a readable error message from an API response.
     */
    if (!xhr) {
        return fallbackMessage || i18n.t("shared.api.request_failed");
    }

    if (xhr.responseJSON) {
        const data = xhr.responseJSON;

        if (Array.isArray(data.details) && data.details.length) {
            const title = translateKnownApiMessage(data.message || data.error || fallbackMessage || i18n.t("shared.api.validation_failed"));

            const details = data.details.map(function (item) {
                const field = item.field ||
                    (Array.isArray(item.loc) ? item.loc.join(".") : "") ||
                    i18n.t("shared.api.field");

                const message = translateKnownApiMessage(item.message || item.type || i18n.t("shared.api.invalid_value"));

                return "- " + field + ": " + message;
            });

            return title + "\n\n" + details.join("\n");
        }

        if (data.message && data.error && data.message !== data.error) {
            return translateKnownApiMessage(data.message) + "\n\n" + translateKnownApiMessage(data.error);
        }

        if (data.message) {
            return translateKnownApiMessage(data.message);
        }

        if (data.error) {
            return translateKnownApiMessage(data.error);
        }

        if (data.detail) {
            return translateKnownApiMessage(data.detail);
        }

        return JSON.stringify(data, null, 2);
    }

    if (xhr.responseText) {
        return translateKnownApiMessage(xhr.responseText);
    }

    return fallbackMessage || i18n.t("shared.api.request_failed");
}


function showApiError(xhr, fallbackMessage) {
    /*
     * Show API error using the global application dialog.
     */
    const status = xhr ? xhr.status : 0;
    const data = xhr && xhr.responseJSON ? xhr.responseJSON : null;
    const message = getApiErrorMessage(xhr, fallbackMessage);

    if (status === 401) {
        showAppError(
            i18n.t("shared.api.session_expired"),
            i18n.t("shared.api.unauthorized")
        ).always(function () {
            if (typeof clearStoredToken === "function") {
                clearStoredToken();
            } else {
                localStorage.removeItem("incidentrelay_jwt");
            }

            if (typeof redirectToLogin === "function") {
                redirectToLogin();
            } else {
                window.location.href = "/login";
            }
        });

        return;
    }

    if (data && data.error === "validation_error") {
        showAppError(message, i18n.t("shared.api.validation_error"));
        return;
    }

    if (status === 403) {
        showAppError(message || i18n.t("shared.api.access_denied"), i18n.t("shared.api.access_denied"));
        return;
    }

    if (status === 404) {
        showAppError(message || i18n.t("shared.api.resource_not_found"), i18n.t("shared.api.not_found"));
        return;
    }

    if (status >= 500) {
        showAppError(message || i18n.t("shared.api.server_error"), i18n.t("shared.api.server_error"));
        return;
    }

    showAppError(message, i18n.t("shared.api.api_error"));
}
function showAppError(message, title) {
    /*
     * Show error dialog.
     */
    return showAppDialog({
        type: "error",
        title: title || i18n.t("shared.dialog.error"),
        message: message || i18n.t("shared.dialog.unexpected_error"),
        confirmText: i18n.t("shared.dialog.close"),
        hideCancel: true
    });
}