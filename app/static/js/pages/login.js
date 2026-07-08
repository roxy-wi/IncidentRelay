function setLoginStatus(message, type) {
    /*
     * Show login page status message.
     */
    $("#login-status")
        .css("display", "block")
        .removeClass("login-status-error login-status-success login-status-info")
        .addClass("login-status-" + (type || "info"))
        .text(message || "");
}

function getLoginReturnUrl() {
    /*
     * Return the safe page URL requested before authentication.
     */
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next");

    if (typeof normalizeReturnPath === "function") {
        return normalizeReturnPath(next, "/");
    }

    return next && next.indexOf("/") === 0 && next.indexOf("//") !== 0 ? next : "/";
}

function login(event) {
    /*
     * Request a JWT token and store it locally.
     */
    if (event) {
        event.preventDefault();
    }

    const username = $("#username").val().trim();
    const password = $("#password").val();

    if (!username || !password) {
        setLoginStatus("Please enter username and password", "error");
        return;
    }

    setLoginStatus("Signing in...", "info");

    apiPost(
        "/api/auth/login",
        {
            username: username,
            password: password
        },
        function (data) {
            localStorage.setItem("incidentrelay_jwt", data.access_token);

            setLoginStatus(
                "Logged in as " + data.user.username + "\nExpires at: " + data.expires_at,
                "success"
            );

            window.location.href = getLoginReturnUrl();
        },
        function (xhr) {
            const message = getApiErrorMessage(
                xhr,
                "Invalid username or password"
            );

            if (xhr && xhr.status === 401) {
                setLoginStatus("Invalid username or password", "error");
                return;
            }

            setLoginStatus(message, "error");
        }
    );
}

function loadLogin() {
    /*
     * Show current login state and load SSO providers.
     */
    const token = localStorage.getItem("incidentrelay_jwt");

    if (token) {
        setLoginStatus("JWT token is stored in this browser.", "info");
    } else {
        $("#login-status").hide().text("");
    }

    loadSsoProviders();
}

$(document).on("submit", "#login-form", login);
$(document).on("click", "#logout-submit", logout);
$(document).ready(loadLogin);
function renderSsoProviders(providers) {
    const section = $("#sso-login-section");
    const container = $("#sso-provider-buttons");

    container.empty();

    providers = Array.isArray(providers) ? providers : [];

    if (!providers.length) {
        section.hide();
        return;
    }

    providers.forEach(function (provider) {
        const protocol = String(provider.protocol || "sso").toUpperCase();
        const protocolClass = "login-sso-button-" + String(provider.protocol || "sso").toLowerCase();
        const label = provider.label || provider.slug || "SSO";
        const iconClass = provider.protocol === "saml"
            ? "fa-solid fa-id-card"
            : "fa-solid fa-right-to-bracket";

        container.append(
            $("<a>")
                .addClass("login-sso-button")
                .addClass(protocolClass)
                .attr(
                    "href",
                    "/api/auth/sso/" + encodeURIComponent(provider.slug) +
                        "/login?next=" + encodeURIComponent(getLoginReturnUrl())
                )
                .append(
                    $("<span>")
                        .addClass("login-sso-icon")
                        .append($("<i>").addClass(iconClass))
                )
                .append(
                    $("<span>")
                        .addClass("login-sso-main")
                        .append($("<span>").addClass("login-sso-title").text("Sign in with " + label))
                        .append($("<span>").addClass("login-sso-subtitle").text("Continue using your identity provider"))
                )
                .append($("<span>").addClass("login-sso-protocol").text(protocol))
        );
    });

    section.show();
}

function loadSsoProviders() {
  $.ajax({
    method: "GET",
    url: "/api/auth/sso/providers",
    success: function (providers) {
      renderSsoProviders(providers);
    },
    error: function () {
      $("#sso-login-section").hide();
    },
  });
}
