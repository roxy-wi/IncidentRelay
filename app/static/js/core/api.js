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
function getApiErrorMessage(xhr, fallbackMessage) {
    /*
     * Extract a readable error message from an API response.
     */
    if (!xhr) {
        return fallbackMessage || "Request failed";
    }

    if (xhr.responseJSON) {
        const data = xhr.responseJSON;

        if (Array.isArray(data.details) && data.details.length) {
            const title = data.message || data.error || fallbackMessage || "Validation failed";

            const details = data.details.map(function (item) {
                const field = item.field ||
                    (Array.isArray(item.loc) ? item.loc.join(".") : "") ||
                    "field";

                const message = item.message || item.type || "Invalid value";

                return "- " + field + ": " + message;
            });

            return title + "\n\n" + details.join("\n");
        }

        if (data.message && data.error && data.message !== data.error) {
            return data.message + "\n\n" + data.error;
        }

        if (data.message) {
            return data.message;
        }

        if (data.error) {
            return data.error;
        }

        if (data.detail) {
            return data.detail;
        }

        return JSON.stringify(data, null, 2);
    }

    if (xhr.responseText) {
        return xhr.responseText;
    }

    return fallbackMessage || "Request failed";
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
            "Your session has expired. Please sign in again.",
            "Unauthorized"
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
        showAppError(message, "Validation error");
        return;
    }

    if (status === 403) {
        showAppError(message || "Access denied", "Access denied");
        return;
    }

    if (status === 404) {
        showAppError(message || "Resource not found", "Not found");
        return;
    }

    if (status >= 500) {
        showAppError(message || "Server error", "Server error");
        return;
    }

    showAppError(message, "API error");
}
function showAppError(message, title) {
    /*
     * Show error dialog.
     */
    return showAppDialog({
        type: "error",
        title: title || "Error",
        message: message || "Unexpected error",
        confirmText: "Close",
        hideCancel: true
    });
}