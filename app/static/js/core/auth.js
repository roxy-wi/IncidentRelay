const INCIDENTRELAY_TOKEN_KEY = "incidentrelay_jwt";

function normalizeReturnPath(value, fallback) {
  /*
   * Normalize a post-login redirect target to a same-origin UI path.
   */
  fallback = fallback || "/";

  if (!value) {
    return fallback;
  }

  try {
    const url = new URL(String(value), window.location.origin);

    if (url.origin !== window.location.origin) {
      return fallback;
    }

    const path = url.pathname + url.search + url.hash;

    if (!path || path === "/login" || path.indexOf("/api/auth/") === 0) {
      return fallback;
    }

    return path;
  } catch (error) {
    return fallback;
  }
}

function currentReturnPath() {
  return normalizeReturnPath(
    window.location.pathname + window.location.search + window.location.hash,
    "/"
  );
}

function loginUrlForReturnPath(returnPath) {
  const target = normalizeReturnPath(returnPath || currentReturnPath(), "/");

  if (target === "/") {
    return "/login";
  }

  return "/login?next=" + encodeURIComponent(target);
}

function redirectToLogin(returnPath) {
  window.location.href = loginUrlForReturnPath(returnPath || currentReturnPath());
}

function getStoredToken() {
  return localStorage.getItem(INCIDENTRELAY_TOKEN_KEY);
}

function clearStoredToken() {
  localStorage.removeItem(INCIDENTRELAY_TOKEN_KEY);
}

function logout() {
  /*
   * Remove local JWT and clear auth cookie on backend.
   */
  apiPost(
    "/api/auth/logout",
    {},
    function () {
      clearStoredToken();
      window.location.href = "/login";
    },
    function () {
      clearStoredToken();
      window.location.href = "/login";
    }
  );
}
