function login(event) {
    /* Request a JWT token and store it locally. */
    if (event) {
        event.preventDefault();
    }

    const username = $("#username").val().trim();
    const password = $("#password").val();

    if (!username || !password) {
        $("#login-status").text("Please enter username and password");
        return;
    }

    apiPost(
        "/api/auth/login",
        {
            username: username,
            password: password
        },
        function (data) {
            localStorage.setItem("oncall_jwt", data.access_token);
            $("#login-status").text(
                "Logged in as " + data.user.username + "\nExpires at: " + data.expires_at
            );
            window.location.href = "/";
        }
    );
}

function logout() {
    /* Remove the stored JWT token and clear the cookie. */
    apiPost("/api/auth/logout", {}, function () {
        localStorage.removeItem("oncall_jwt");
        $("#login-status").text("Logged out");
        window.location.href = "/login";
    });
}

function loadLogin() {
    /* Show current login state. */
    const token = localStorage.getItem("oncall_jwt");
    $("#login-status").text(token ? "JWT token is stored in this browser." : "");
}

$(document).on("submit", "#login-form", login);
$(document).on("click", "#logout-submit", logout);