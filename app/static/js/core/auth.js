const INCIDENTRELAY_TOKEN_KEY = "incidentrelay_jwt";

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
