let ssoProvidersCache = [];
let ssoMappingsCache = [];
let ssoGroupsCache = [];
let ssoTeamsCache = [];
let selectedSsoProvider = null;
let ssoProviderExtraConfigCache = {};

function ssoRoleLabel(role, scope) {
  if (!role) {
    return "—";
  }

  const normalized = String(role);
  const key = "sso.roles." + (scope === "team" ? "team" : "group") + "." + normalized;
  return i18n.t(key, {}, normalized.replace(/_/g, " "));
}


function fillSamlSecurityFields(provider) {
  const security = provider && provider.saml_security ? provider.saml_security : {};

  $("#sso-saml-authn-requests-signed").prop("checked", !!security.authnRequestsSigned);
  $("#sso-saml-logout-request-signed").prop("checked", !!security.logoutRequestSigned);
  $("#sso-saml-logout-response-signed").prop("checked", !!security.logoutResponseSigned);
  $("#sso-saml-sign-metadata").prop("checked", !!security.signMetadata);
  $("#sso-saml-want-messages-signed").prop("checked", !!security.wantMessagesSigned);
  $("#sso-saml-want-assertions-signed").prop("checked", !!security.wantAssertionsSigned);
  $("#sso-saml-want-name-id-encrypted").prop("checked", !!security.wantNameIdEncrypted);
  $("#sso-saml-want-assertions-encrypted").prop("checked", !!security.wantAssertionsEncrypted);
  $("#sso-saml-want-attribute-statement").prop("checked", !!security.wantAttributeStatement);
}

function collectSamlSecurityPayload() {
  return {
    authnRequestsSigned: $("#sso-saml-authn-requests-signed").is(":checked"),
    logoutRequestSigned: $("#sso-saml-logout-request-signed").is(":checked"),
    logoutResponseSigned: $("#sso-saml-logout-response-signed").is(":checked"),
    signMetadata: $("#sso-saml-sign-metadata").is(":checked"),
    wantMessagesSigned: $("#sso-saml-want-messages-signed").is(":checked"),
    wantAssertionsSigned: $("#sso-saml-want-assertions-signed").is(":checked"),
    wantNameIdEncrypted: $("#sso-saml-want-name-id-encrypted").is(":checked"),
    wantAssertionsEncrypted: $("#sso-saml-want-assertions-encrypted").is(":checked"),
    wantAttributeStatement: $("#sso-saml-want-attribute-statement").is(":checked"),
  };
}

function loadSsoAdmin() {
  loadSsoGroups(function () {
    loadSsoTeams(function () {
      loadSsoProviders();
    });
  });
}

function loadSsoGroups(done) {
  apiGet("/api/groups", function (groups) {
    ssoGroupsCache = asArray(groups).filter(function (group) {
      return !!group.active;
    });

    fillSsoGroupSelect();

    if (typeof done === "function") {
      done();
    }
  });
}

function fillSsoGroupSelect(selectedValue) {
  const select = $("#sso-mapping-group");
  select.empty();

  ssoGroupsCache.forEach(function (group) {
    select.append(
      $("<option>")
        .val(String(group.id))
        .text((group.name || group.slug || i18n.t("groups.row.fallback", {id: group.id}, "Group #" + group.id)) + " (" + group.slug + ")")
    );
  });

  if (selectedValue) {
    select.val(String(selectedValue));
  }
}

function loadSsoTeams(done) {
  apiGet("/api/teams?include_inactive=true", function (teams) {
    ssoTeamsCache = asArray(teams).filter(function (team) {
      return team.active !== false;
    });

    fillSsoTeamSelect();

    if (typeof done === "function") {
      done();
    }
  });
}

function getSsoTeamsForSelectedGroup() {
  const groupId = Number($("#sso-mapping-group").val());

  if (!groupId) {
    return [];
  }

  return ssoTeamsCache.filter(function (team) {
    return Number(team.group_id) === groupId;
  });
}

function fillSsoTeamSelect(selectedValue) {
  const select = $("#sso-mapping-team");
  const teams = getSsoTeamsForSelectedGroup();

  select.empty();
  select.append(
    $("<option>")
      .val("")
      .text(i18n.t("sso.mappings.no_team"))
  );

  teams.forEach(function (team) {
    select.append(
      $("<option>")
        .val(String(team.id))
        .text((team.name || team.slug || i18n.t("teams.row.team_id", {id: team.id}, "Team #" + team.id)) + " (" + team.slug + ")")
    );
  });

  if (selectedValue && select.find('option[value="' + selectedValue + '"]').length) {
    select.val(String(selectedValue));
  } else {
    select.val("");
  }

  $("#sso-mapping-team-role").prop("disabled", !select.val());
}

function loadSsoProviders() {
  apiGet("/api/admin/sso/providers", function (providers) {
    ssoProvidersCache = asArray(providers);
    renderSsoProviders();
    renderSsoSummary(ssoProvidersCache);

    if (selectedSsoProvider) {
      const stillExists = ssoProvidersCache.find(function (provider) {
        return Number(provider.id) === Number(selectedSsoProvider.id);
      });

      if (stillExists) {
        selectedSsoProvider = stillExists;
        loadSsoMappings(stillExists);
      } else {
        clearSsoMappings();
      }
    }
  });
}

function getFilteredSsoProviders() {
  const search = ($("#sso-search").val() || "").trim().toLowerCase();
  const protocol = $("#sso-protocol-filter").val();
  const status = $("#sso-status-filter").val();

  return ssoProvidersCache.filter(function (provider) {
    const haystack = [
      provider.slug,
      provider.label,
      provider.protocol,
      provider.oidc_metadata_url,
      provider.saml_idp_entity_id,
    ].join(" ").toLowerCase();

    if (search && haystack.indexOf(search) === -1) {
      return false;
    }

    if (protocol && provider.protocol !== protocol) {
      return false;
    }

    if (status === "enabled" && !provider.enabled) {
      return false;
    }

    if (status === "disabled" && provider.enabled) {
      return false;
    }

    return true;
  });
}

function renderSsoProviders() {
  const providers = getFilteredSsoProviders();
  const tbody = $("#sso-providers-table");

  tbody.empty();

  $("#sso-filtered-count").text(providers.length);
  $("#sso-total-count").text(ssoProvidersCache.length);

  if (!providers.length) {
    tbody.append(
      $("<tr>").append(
        $("<td>")
          .attr("colspan", "7")
          .addClass("empty-muted")
          .text(i18n.t("sso.empty.providers"))
      )
    );
    return;
  }

  providers.forEach(function (provider) {
    tbody.append(renderSsoProviderRow(provider));
  });
}

function renderSsoProviderRow(provider) {
  const row = $("<tr>").toggleClass("row-disabled", !provider.enabled);

  row.append($("<td>").text(provider.id));

  row.append(
    $("<td>")
      .append(
        $("<button>")
          .attr("type", "button")
          .addClass("name-button")
          .text(provider.label || provider.slug)
          .on("click", function () {
            openSsoMappingsModal(provider);
          })
      )
      .append(
        $("<div>")
          .addClass("details-meta")
          .text(provider.slug || "-")
      )
  );

  row.append(
    $("<td>").append(
      $("<span>")
        .addClass("status-pill")
        .text(String(provider.protocol || "sso").toUpperCase())
    )
  );

  row.append(
    $("<td>").append(
      $("<span>")
        .addClass("status-pill")
        .addClass(provider.enabled ? "status-active" : "status-inactive")
        .text(provider.enabled ? i18n.t("sso.status.enabled") : i18n.t("sso.status.disabled"))
    )
  );

  row.append($("<td>").text(provider.auto_create_users ? i18n.t("sso.values.yes") : i18n.t("sso.values.no")));
  row.append($("<td>").text(provider.sync_group_memberships ? i18n.t("sso.values.yes") : i18n.t("sso.values.no")));

  row.append(
    $("<td>")
      .addClass("actions-cell")
      .append(renderSsoProviderActions(provider))
  );

  return row;
}

function renderSsoProviderActions(provider) {
  return makeActionMenu({
    object: provider,
    items: [
      {
        label: i18n.t("sso.actions.mappings"),
        icon: "fas fa-project-diagram",
        onClick: function () {
          openSsoMappingsModal(provider);
        }
      },
      {
        label: i18n.t("sso.actions.edit"),
        icon: "fas fa-edit",
        onClick: function () {
          openExistingSsoProviderModal(provider);
        }
      },
      {
        label: i18n.t("sso.actions.test"),
        icon: "fas fa-external-link-alt",
        onClick: function () {
          window.open(
              "/api/auth/sso/" + encodeURIComponent(provider.slug) + "/login",
              "_blank"
          );
        }
      },
      {
        label: i18n.t("sso.actions.metadata"),
        icon: "fas fa-file-code",
        visible: function () {
          return provider.protocol === "saml";
        },
        onClick: function () {
          window.open(
              "/api/auth/sso/" + encodeURIComponent(provider.slug) + "/metadata",
              "_blank"
          );
        }
      },
      {
        label: provider.enabled ? i18n.t("sso.actions.disable") : i18n.t("sso.actions.enable"),
        icon: provider.enabled ? "fas fa-pause" : "fas fa-play",
        danger: provider.enabled,
        onClick: function () {
          toggleSsoProviderEnabled(provider);
        }
      },
      {
        label: i18n.t("sso.actions.delete"),
        icon: "fas fa-trash",
        danger: true,
        onClick: function () {
          deleteSsoProvider(provider);
        }
      }
    ]
  });
}

function openSsoMappingsModal(provider) {
  /*
   * Open mappings list modal for selected SSO provider.
   */
  selectedSsoProvider = provider;

  $("#sso-mappings-modal-title").text(i18n.t("sso.mappings.title_provider", {provider: provider.label || provider.slug}));
  $("#sso-mappings-modal-subtitle").text(
      i18n.t("sso.mappings.provider_subtitle", {provider: provider.slug || provider.id})
  );

  $("#sso-mappings-body").html(
      $("<div>")
          .addClass("details-empty")
          .text(i18n.t("sso.mappings.loading"))
  );

  openAppModal("#sso-mappings-modal");
  loadSsoMappings(provider);
}

function clearSsoMappings() {
  selectedSsoProvider = null;
  ssoMappingsCache = [];

  $("#sso-mappings-modal-title").text(i18n.t("sso.mappings.title"));
  $("#sso-mappings-modal-subtitle").text(i18n.t("sso.mappings.list_subtitle"));
  $("#sso-mappings-body").html(
      $("<div>")
          .addClass("details-empty")
          .text(i18n.t("sso.mappings.select_provider"))
  );
}

function loadSsoMappings(provider) {
  if (!provider) {
    clearSsoMappings();
    return;
  }

  apiGet("/api/admin/sso/providers/" + provider.id + "/mappings", function (mappings) {
    ssoMappingsCache = asArray(mappings);
    renderSsoMappings();
  });
}

function renderSsoMappings() {
  const body = $("#sso-mappings-body");
  body.empty();

  if (!selectedSsoProvider) {
    body.append(
        $("<div>")
            .addClass("details-empty")
            .text(i18n.t("sso.mappings.select_provider"))
    );
    return;
  }

  if (!ssoMappingsCache.length) {
    body.append(
        $("<div>")
            .addClass("details-empty")
            .text(i18n.t("sso.mappings.empty"))
    );
    return;
  }

  ssoMappingsCache.forEach(function (mapping) {
    body.append(renderSsoMappingCard(mapping));
  });
}

function renderSsoMappingCard(mapping) {
  const card = $("<div>")
      .addClass("stack-card")
      .toggleClass("row-disabled", !mapping.active);

  card.append(
      $("<div>")
          .addClass("stack-card-header")
          .append(
              $("<div>")
                  .addClass("stack-card-title")
                  .append(
                      $("<div>")
                          .addClass("stack-card-title-main")
                          .text(mapping.external_group)
                  )
                  .append(
                      $("<div>")
                          .addClass("stack-card-title-sub")
                          .text(
                              (mapping.group_name || mapping.group_slug || i18n.t("sso.mappings.group_fallback")) +
                              " · " +
                              ssoRoleLabel(mapping.group_role || "viewer", "group") +
                              (mapping.team_id
                                ? " · " + (mapping.team_name || mapping.team_slug || i18n.t("sso.mappings.team_fallback")) + " / " + ssoRoleLabel(mapping.team_role || "viewer", "team")
                                : "")
                          )
                  )
          )
          .append(
              $("<div>")
                  .addClass("stack-card-actions")
                  .append(renderSsoMappingActions(mapping))
          )
  );

  card.append(
      $("<div>")
          .addClass("summary-mini-grid")
          .append(renderSsoMiniItem(i18n.t("sso.mappings.ir_group"), mapping.group_name || mapping.group_slug))
          .append(renderSsoMiniItem(i18n.t("sso.mappings.group_role"), ssoRoleLabel(mapping.group_role || "viewer", "group")))
          .append(renderSsoMiniItem(i18n.t("sso.mappings.ir_team"), mapping.team_name || mapping.team_slug || "—"))
          .append(renderSsoMiniItem(i18n.t("sso.mappings.team_role"), mapping.team_role ? ssoRoleLabel(mapping.team_role, "team") : "—"))
          .append(renderSsoMiniItem(i18n.t("sso.mappings.priority"), mapping.priority))
          .append(renderSsoMiniItem(i18n.t("sso.table.status"), mapping.active ? i18n.t("sso.status.enabled") : i18n.t("sso.status.disabled")))
  );

  return card;
}
function renderSsoMappingActions(mapping) {
  return makeActionMenu({
    object: mapping,
    items: [
      {
        label: i18n.t("sso.actions.edit"),
        icon: "fas fa-edit",
        onClick: function () {
          openExistingSsoMappingModal(mapping);
        }
      },
      {
        label: i18n.t("sso.actions.delete"),
        icon: "fas fa-trash",
        danger: true,
        onClick: function () {
          deleteSsoMapping(mapping);
        }
      }
    ]
  });
}
function renderSsoMiniItem(label, value) {
  return $("<div>")
    .addClass("summary-mini-item")
    .append($("<div>").addClass("summary-mini-label").text(label))
    .append($("<div>").addClass("summary-mini-value").text(value || "-"));
}


function openNewSsoProviderModal() {
  resetSsoProviderForm();
  $("#sso-provider-modal-title").text(i18n.t("sso.provider.new"));
  $("#sso-provider-modal-subtitle").text(i18n.t("sso.provider.subtitle"));
  openAppModal("#sso-provider-modal");
}

function openExistingSsoProviderModal(provider) {
  resetSsoProviderForm();

  $("#sso-provider-id").val(provider.id);
  $("#sso-provider-slug").val(provider.slug || "");
  $("#sso-provider-label").val(provider.label || "");
  $("#sso-provider-protocol").val(provider.protocol || "oidc");
  $("#sso-provider-enabled").prop("checked", !!provider.enabled);

  $("#sso-subject-claim").val(provider.subject_claim || "sub");
  $("#sso-email-claim").val(provider.email_claim || "email");
  $("#sso-username-claim").val(provider.username_claim || "preferred_username");
  $("#sso-display-name-claim").val(provider.display_name_claim || "name");
  $("#sso-groups-claim").val(provider.groups_claim || "groups");
  $("#sso-phone-claim").val(provider.phone_claim || "mobile");
  $("#sso-allowed-domains").val((provider.allowed_domains || []).join(", "));

  $("#sso-auto-create-users").prop("checked", !!provider.auto_create_users);
  $("#sso-auto-link-by-email").prop("checked", !!provider.auto_link_by_email);
  $("#sso-require-verified-email").prop("checked", !!provider.require_verified_email);
  $("#sso-sync-group-memberships").prop("checked", !!provider.sync_group_memberships);
  $("#sso-remove-missing-group-memberships").prop("checked", !!provider.remove_missing_group_memberships);

  $("#sso-client-id").val(provider.client_id || "");
  $("#sso-client-secret").val("");
  $("#sso-oidc-metadata-url").val(provider.oidc_metadata_url || "");
  $("#sso-oidc-scope").val(provider.oidc_scope || "openid email profile");
  $("#sso-oidc-issuer").val(provider.oidc_issuer || "");
  $("#sso-oidc-authorization-endpoint").val(provider.oidc_authorization_endpoint || "");
  $("#sso-oidc-token-endpoint").val(provider.oidc_token_endpoint || "");
  $("#sso-oidc-userinfo-endpoint").val(provider.oidc_userinfo_endpoint || "");
  $("#sso-oidc-jwks-uri").val(provider.oidc_jwks_uri || "");

  $("#sso-saml-idp-entity-id").val(provider.saml_idp_entity_id || "");
  $("#sso-saml-idp-sso-url").val(provider.saml_idp_sso_url || "");
  $("#sso-saml-idp-slo-url").val(provider.saml_idp_slo_url || "");
  $("#sso-saml-idp-x509-cert").val(provider.saml_idp_x509_cert || "");
  $("#sso-saml-idp-metadata-url").val(provider.saml_idp_metadata_url || "");
  $("#sso-saml-sp-entity-id").val(provider.saml_sp_entity_id || "");
  $("#sso-saml-sp-acs-url").val(provider.saml_sp_acs_url || "");

  $("#sso-provider-modal-title").text(i18n.t("sso.provider.edit"));
  $("#sso-provider-modal-subtitle").text(provider.label || provider.slug);

  ssoProviderExtraConfigCache = provider.extra_config || {};

  $("#sso-saml-sp-sls-url").val(provider.saml_sp_sls_url || "");
  $("#sso-saml-sp-x509-cert").val(provider.saml_sp_x509_cert || "");
  $("#sso-saml-sp-private-key").val("");
  $("#sso-saml-name-id-format").val(
      provider.saml_name_id_format || "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
  );

  fillSamlSecurityFields(provider);
  toggleSsoProtocolFields();
  openAppModal("#sso-provider-modal");
}

function resetSsoProviderForm() {
  $("#sso-provider-id").val("");
  $("#sso-provider-slug").val("");
  $("#sso-provider-label").val("");
  $("#sso-provider-protocol").val("oidc");
  $("#sso-provider-enabled").prop("checked", true);

  $("#sso-subject-claim").val("sub");
  $("#sso-email-claim").val("email");
  $("#sso-username-claim").val("preferred_username");
  $("#sso-display-name-claim").val("name");
  $("#sso-groups-claim").val("groups");
  $("#sso-phone-claim").val("mobile");
  $("#sso-allowed-domains").val("");

  $("#sso-auto-create-users").prop("checked", false);
  $("#sso-auto-link-by-email").prop("checked", true);
  $("#sso-require-verified-email").prop("checked", true);
  $("#sso-sync-group-memberships").prop("checked", true);
  $("#sso-remove-missing-group-memberships").prop("checked", false);
  $("#sso-oidc-issuer").val("");

  $("#sso-client-id").val("");
  $("#sso-client-secret").val("");
  $("#sso-oidc-metadata-url").val("");
  $("#sso-oidc-scope").val("openid email profile");
  $("#sso-oidc-authorization-endpoint").val("");
  $("#sso-oidc-token-endpoint").val("");
  $("#sso-oidc-userinfo-endpoint").val("");
  $("#sso-oidc-jwks-uri").val("");

  $("#sso-saml-idp-entity-id").val("");
  $("#sso-saml-idp-sso-url").val("");
  $("#sso-saml-idp-slo-url").val("");
  $("#sso-saml-idp-x509-cert").val("");
  $("#sso-saml-idp-metadata-url").val("");
  $("#sso-saml-metadata-status").text("");
  $("#sso-saml-sp-entity-id").val("");
  $("#sso-saml-sp-acs-url").val("");

  ssoProviderExtraConfigCache = {};

  $("#sso-saml-sp-sls-url").val("");
  $("#sso-saml-sp-x509-cert").val("");
  $("#sso-saml-sp-private-key").val("");
  $("#sso-saml-name-id-format").val("urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress");

  fillSamlSecurityFields(null);
  toggleSsoProtocolFields();
}

function collectSsoProviderPayload() {
  const protocol = $("#sso-provider-protocol").val();
  const domains = ($("#sso-allowed-domains").val() || "")
      .split(",")
      .map(function (item) {
        return item.trim().toLowerCase();
      })
      .filter(Boolean);

  const payload = {
    slug: $("#sso-provider-slug").val().trim(),
    label: $("#sso-provider-label").val().trim(),
    protocol: protocol,
    enabled: $("#sso-provider-enabled").is(":checked"),

    subject_claim: $("#sso-subject-claim").val().trim() || (protocol === "saml" ? "NameID" : "sub"),
    email_claim: $("#sso-email-claim").val().trim() || "email",
    username_claim: $("#sso-username-claim").val().trim() || "preferred_username",
    display_name_claim: $("#sso-display-name-claim").val().trim() || "name",
    groups_claim: $("#sso-groups-claim").val().trim() || "groups",
    phone_claim: $("#sso-phone-claim").val().trim() || "mobile",

    allowed_domains: domains.length ? domains : null,

    auto_create_users: $("#sso-auto-create-users").is(":checked"),
    auto_link_by_email: $("#sso-auto-link-by-email").is(":checked"),
    require_verified_email: $("#sso-require-verified-email").is(":checked"),
    sync_group_memberships: $("#sso-sync-group-memberships").is(":checked"),
    remove_missing_group_memberships: $("#sso-remove-missing-group-memberships").is(":checked"),

    client_id: $("#sso-client-id").val().trim() || null,
    client_secret: $("#sso-client-secret").val() || null,
    oidc_metadata_url: $("#sso-oidc-metadata-url").val().trim() || null,
    oidc_scope: $("#sso-oidc-scope").val().trim() || "openid email profile",
    oidc_authorization_endpoint: $("#sso-oidc-authorization-endpoint").val().trim() || null,
    oidc_issuer: $("#sso-oidc-issuer").val().trim() || null,
    oidc_token_endpoint: $("#sso-oidc-token-endpoint").val().trim() || null,
    oidc_userinfo_endpoint: $("#sso-oidc-userinfo-endpoint").val().trim() || null,
    oidc_jwks_uri: $("#sso-oidc-jwks-uri").val().trim() || null,

    saml_idp_entity_id: $("#sso-saml-idp-entity-id").val().trim() || null,
    saml_idp_sso_url: $("#sso-saml-idp-sso-url").val().trim() || null,
    saml_idp_slo_url: $("#sso-saml-idp-slo-url").val().trim() || null,
    saml_idp_x509_cert: $("#sso-saml-idp-x509-cert").val().trim() || null,
    saml_idp_metadata_url: $("#sso-saml-idp-metadata-url").val().trim() || null,
    saml_sp_entity_id: $("#sso-saml-sp-entity-id").val().trim() || null,
    saml_sp_acs_url: $("#sso-saml-sp-acs-url").val().trim() || null,

    saml_sp_sls_url: $("#sso-saml-sp-sls-url").val().trim() || null,
    saml_sp_x509_cert: $("#sso-saml-sp-x509-cert").val().trim() || null,
    saml_sp_private_key: $("#sso-saml-sp-private-key").val().trim() || null,
    saml_name_id_format: $("#sso-saml-name-id-format").val().trim() || "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
  };

  const extraConfig = Object.assign({}, ssoProviderExtraConfigCache || {});
  extraConfig.saml_security = collectSamlSecurityPayload();
  payload.extra_config = extraConfig;

  return payload;
}

function saveSsoProvider() {
  const providerId = $("#sso-provider-id").val();
  const payload = collectSsoProviderPayload();

  if (!payload.slug || !payload.label) {
    showAppError(i18n.t("sso.validation.slug_label"));
    return;
  }

  if (payload.protocol === "oidc" && !payload.client_id) {
    showAppError(i18n.t("sso.validation.oidc_client"));
    return;
  }

  if (payload.protocol === "saml" && (!payload.saml_idp_entity_id || !payload.saml_idp_sso_url)) {
    showAppError(i18n.t("sso.validation.saml_idp"));
    return;
  }

  if (providerId) {
    apiPut("/api/admin/sso/providers/" + providerId, payload, function (provider) {
      closeAppModal("#sso-provider-modal");
      selectedSsoProvider = provider;
      loadSsoProviders();
    });
    return;
  }

  apiPost("/api/admin/sso/providers", payload, function (provider) {
    closeAppModal("#sso-provider-modal");
    selectedSsoProvider = provider;
    loadSsoProviders();
  });
}

function deleteSsoProvider(provider) {
  showAppConfirm({
    title: i18n.t("sso.confirm.delete_provider_title"),
    message: i18n.t("sso.confirm.delete_provider_message", {provider: provider.label || provider.slug}),
    confirmText: i18n.t("sso.actions.delete"),
    confirmClass: "btn-danger",
  }).done(function () {
    apiDelete("/api/admin/sso/providers/" + provider.id, function () {
      if (selectedSsoProvider && Number(selectedSsoProvider.id) === Number(provider.id)) {
        clearSsoMappings();
      }
      loadSsoProviders();
    });
  });
}

function toggleSsoProtocolFields() {
  const protocol = $("#sso-provider-protocol").val();

  if (protocol === "saml") {
    $("#sso-oidc-settings")
        .addClass("is-hidden")
        .prop("hidden", true)
        .css("display", "none");

    $("#sso-saml-settings")
        .removeClass("is-hidden")
        .prop("hidden", false)
        .css("display", "block");

    if ($("#sso-subject-claim").val() === "sub") {
      $("#sso-subject-claim").val("NameID");
    }

    return;
  }

  $("#sso-saml-settings")
      .addClass("is-hidden")
      .prop("hidden", true)
      .css("display", "none");

  $("#sso-oidc-settings")
      .removeClass("is-hidden")
      .prop("hidden", false)
      .css("display", "block");

  if ($("#sso-subject-claim").val() === "NameID") {
    $("#sso-subject-claim").val("sub");
  }
}

function openNewSsoMappingModal() {
  if (!selectedSsoProvider) {
    showAppError(i18n.t("sso.validation.select_provider"));
    return;
  }

  resetSsoMappingForm();
  $("#sso-mapping-modal-title").text(i18n.t("sso.mappings.new"));
  $("#sso-mapping-modal-subtitle").text(selectedSsoProvider.label || selectedSsoProvider.slug);
  openAppModal("#sso-mapping-modal");
}

function openExistingSsoMappingModal(mapping) {
  resetSsoMappingForm();

  $("#sso-mapping-id").val(mapping.id);
  $("#sso-mapping-external-group").val(mapping.external_group || "");
  fillSsoGroupSelect(mapping.group_id);
  fillSsoTeamSelect(mapping.team_id);
  $("#sso-mapping-role").val(mapping.group_role || "viewer");
  $("#sso-mapping-team-role").val(mapping.team_role || "viewer");
  $("#sso-mapping-team-role").prop("disabled", !mapping.team_id);
  $("#sso-mapping-priority").val(mapping.priority || 100);
  $("#sso-mapping-active").prop("checked", !!mapping.active);

  $("#sso-mapping-modal-title").text(i18n.t("sso.mappings.edit"));
  $("#sso-mapping-modal-subtitle").text(mapping.external_group || "");
  openAppModal("#sso-mapping-modal");
}

function resetSsoMappingForm() {
  $("#sso-mapping-id").val("");
  $("#sso-mapping-external-group").val("");
  fillSsoGroupSelect();
  fillSsoTeamSelect();
  $("#sso-mapping-role").val("viewer");
  $("#sso-mapping-team-role").val("viewer");
  $("#sso-mapping-team-role").prop("disabled", true);
  $("#sso-mapping-priority").val(100);
  $("#sso-mapping-active").prop("checked", true);
}

function collectSsoMappingPayload() {
  return {
    external_group: $("#sso-mapping-external-group").val().trim(),
    group_id: Number($("#sso-mapping-group").val()),
    group_role: $("#sso-mapping-role").val() || "viewer",
    team_id: $("#sso-mapping-team").val() ? Number($("#sso-mapping-team").val()) : null,
    team_role: $("#sso-mapping-team").val() ? ($("#sso-mapping-team-role").val() || "viewer") : null,
    active: $("#sso-mapping-active").is(":checked"),
    priority: Number($("#sso-mapping-priority").val() || 100),
  };
}

function saveSsoMapping() {
  if (!selectedSsoProvider) {
    showAppError(i18n.t("sso.validation.select_provider"));
    return;
  }

  const mappingId = $("#sso-mapping-id").val();
  const payload = collectSsoMappingPayload();

  if (!payload.external_group) {
    showAppError(i18n.t("sso.validation.external_group"));
    return;
  }

  if (!payload.group_id) {
    showAppError(i18n.t("sso.validation.ir_group"));
    return;
  }

  if (mappingId) {
    apiPut("/api/admin/sso/mappings/" + mappingId, payload, function () {
      closeAppModal("#sso-mapping-modal");
      loadSsoMappings(selectedSsoProvider);
    });
    return;
  }

  apiPost("/api/admin/sso/providers/" + selectedSsoProvider.id + "/mappings", payload, function () {
    closeAppModal("#sso-mapping-modal");
    loadSsoMappings(selectedSsoProvider);
  });
}

function deleteSsoMapping(mapping) {
  showAppConfirm({
    title: i18n.t("sso.confirm.delete_mapping_title"),
    message: i18n.t("sso.confirm.delete_mapping_message", {group: mapping.external_group}),
    confirmText: i18n.t("sso.actions.delete"),
    confirmClass: "btn-danger",
  }).done(function () {
    apiDelete("/api/admin/sso/mappings/" + mapping.id, function () {
      loadSsoMappings(selectedSsoProvider);
    });
  });
}

$(document).on("click", "#reload-sso-providers", loadSsoProviders);
$(document).on("click", "#open-sso-provider-create-modal", openNewSsoProviderModal);
$(document).on("click", "#save-sso-provider", saveSsoProvider);
$(document).on("click", "#reset-sso-provider-form", resetSsoProviderForm);
$(document).on("click", "#close-sso-provider-modal", closeAppModal);
$(document).on("change", "#sso-provider-protocol", toggleSsoProtocolFields);

$(document).on("input change", "#sso-search, #sso-protocol-filter, #sso-status-filter", renderSsoProviders);

$(document).on("click", "#add-sso-mapping", openNewSsoMappingModal);

$(document).on("click", "#reload-sso-mappings", function () {
  if (selectedSsoProvider) {
    loadSsoMappings(selectedSsoProvider);
  }
});

$(document).on("click", "#save-sso-mapping", saveSsoMapping);
$(document).on("click", "#reset-sso-mapping-form", resetSsoMappingForm);
$(document).on("change", "#sso-mapping-group", function () {
  fillSsoTeamSelect();
});
$(document).on("change", "#sso-mapping-team", function () {
  $("#sso-mapping-team-role").prop("disabled", !$(this).val());
});
$(document).on("click", "#close-sso-mapping-modal", closeAppModal);
$(document).on("click", "#close-sso-mappings-modal", closeAppModal);

$(document).on("click", "#sso-provider-modal", function (event) {
  if (event.target === this) {
    closeAppModal("#sso-provider-modal");
  }
});

$(document).on("click", "#sso-mapping-modal", function (event) {
  if (event.target === this) {
    closeAppModal("#sso-mapping-modal");
  }
});

$(document).on("keydown", function (event) {
  if (event.key !== "Escape") {
    return;
  }

  if (!$("#sso-mapping-modal").hasClass("is-hidden")) {
    closeAppModal("#sso-mapping-modal");
    return;
  }

  if (!$("#sso-provider-modal").hasClass("is-hidden")) {
    closeAppModal("#sso-provider-modal");
  }
});
function toggleSsoProviderEnabled(provider) {
  /*
   * Enable or disable an SSO provider without deleting it.
   */
  const enabled = !provider.enabled;
  const action = enabled ? i18n.t("sso.confirm.enable_action") : i18n.t("sso.confirm.disable_action");
  const label = provider.label || provider.slug || i18n.t("sso.provider.fallback");

  showAppConfirm({
    title: enabled ? i18n.t("sso.confirm.enable_title") : i18n.t("sso.confirm.disable_title"),
    message: i18n.t("sso.confirm.toggle_message", {action: action, provider: label}),
    confirmText: enabled ? i18n.t("sso.actions.enable") : i18n.t("sso.actions.disable"),
    confirmClass: enabled ? "btn-primary" : "btn-warning",
  }).done(function () {
    apiPut(
        "/api/admin/sso/providers/" + provider.id,
        {
          enabled: enabled,
        },
        function () {
          loadSsoAdmin();
        }
    );
  });
}
function fetchSamlMetadata() {
  /*
   * Fetch SAML IdP metadata and fill provider form fields.
   */
  const metadataUrl = $("#sso-saml-idp-metadata-url").val().trim();
  const status = $("#sso-saml-metadata-status");

  status.text("");

  if (!metadataUrl) {
    status.text(i18n.t("sso.metadata.url_required"));
    return;
  }

  status.text(i18n.t("sso.metadata.fetching"));

  apiPost(
      "/api/admin/sso/saml/metadata/parse",
      {
        metadata_url: metadataUrl,
      },
      function (metadata) {
        $("#sso-saml-idp-metadata-url").val(metadata.metadata_url || metadataUrl);
        $("#sso-saml-idp-entity-id").val(metadata.saml_idp_entity_id || "");
        $("#sso-saml-idp-sso-url").val(metadata.saml_idp_sso_url || "");
        $("#sso-saml-idp-slo-url").val(metadata.saml_idp_slo_url || "");
        $("#sso-saml-idp-x509-cert").val(metadata.saml_idp_x509_cert || "");

        status.text(i18n.t("sso.metadata.loaded"));
      },
      function () {
        status.text(i18n.t("sso.metadata.failed"));
      }
  );
}
$(document).on("click", "#fetch-saml-metadata", fetchSamlMetadata);
function renderSsoSummary(providers) {
  /*
   * Render SSO summary cards.
   */
  providers = asArray(providers);

  const enabled = providers.filter(function (provider) {
    return !!provider.enabled;
  }).length;

  const oidc = providers.filter(function (provider) {
    return provider.protocol === "oidc";
  }).length;

  const saml = providers.filter(function (provider) {
    return provider.protocol === "saml";
  }).length;

  $("#sso-summary-total").text(providers.length);
  $("#sso-summary-enabled").text(enabled);
  $("#sso-summary-disabled").text(providers.length - enabled);
  $("#sso-summary-oidc").text(oidc);
  $("#sso-summary-saml").text(saml);
}