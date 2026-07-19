---
title: SSO
description: Configure OIDC and SAML single sign-on in IncidentRelay.
---

# SSO

IncidentRelay supports authentication through external Identity Providers using:

- OIDC
- SAML 2.0

SSO providers are configured in the admin UI:

```text
Admin → SSO
```

The page is available only to IncidentRelay administrators.

---

## How SSO Works

1. An administrator creates an SSO provider.
2. A user opens the IncidentRelay login page.
3. If the provider is enabled, the SSO login button appears on `/login`.
4. The user is redirected to the external Identity Provider.
5. After successful authentication, the Identity Provider redirects the user back to IncidentRelay.
6. IncidentRelay reads user claims and finds, links, or creates a local user.
7. If group synchronization is enabled, IncidentRelay applies group mappings.

---

## Supported Protocols

### OIDC

OIDC can be used with Keycloak, Authentik, Zitadel, Dex, Azure AD / Entra ID, and other OIDC-compatible providers.

Typical OIDC settings:

```text
Issuer URL
Client ID
Client Secret
Scopes
Redirect URI
```

IncidentRelay callback URL:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

Example for provider slug `keycloak`:

```text
https://incidentrelay.example.com/api/auth/sso/keycloak/callback
```

---

### SAML 2.0

SAML can be used with ADFS, Keycloak SAML, Okta SAML, Authentik SAML, and other SAML Identity Providers.

Typical SAML settings:

```text
IdP Entity ID
IdP SSO URL
IdP SLO URL
IdP x509 certificate
SP Entity ID
ACS URL
SLS URL
NameID format
```

IncidentRelay ACS URL:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

IncidentRelay SAML metadata URL:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/metadata
```

Example for provider slug `adfs`:

```text
https://incidentrelay.example.com/api/auth/sso/adfs/callback
https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

---

## Provider Settings

### Basic Fields

| Field | Description |
|---|---|
| `Slug` | Unique provider name. It is used in URLs. Example: `keycloak`, `adfs`, `corp-sso`. |
| `Label` | Human-readable provider name. It is shown on the login page. |
| `Protocol` | `oidc` or `saml`. |
| `Enabled` | If disabled, the provider is not shown on the login page. |

---

## Claims

IncidentRelay uses claims to connect an external user identity with a local IncidentRelay user.

Recommended claims:

```text
subject / NameID
email
username
displayName
groups
mobile
```

### Claim Fields in IncidentRelay

| Field | Purpose                                                            |
|---|--------------------------------------------------------------------|
| `Subject claim` | Stable unique user identifier from the external Identity Provider. |
| `Email claim` | User email address.                                                |
| `Username claim` | User login or username.                                            |
| `Display name claim` | User display name.                                                 |
| `Groups claim` | List of external groups assigned to the user.                      |
| `Phone claim` | User phone number.                                                 |

---

## Recommended OIDC Claims

For most OIDC providers, use:

```text
Subject claim: sub
Email claim: email
Username claim: preferred_username
Display name claim: name
Groups claim: groups
```

Some Identity Providers use a different claim for groups:

```text
groups
roles
realm_access.roles
resource_access.<client_id>.roles
```

If the provider returns nested claims, use the full dot-separated path.

Example:

```text
Groups claim: realm_access.roles
```

---

## Recommended SAML / ADFS Claims

For SAML, short claim names are recommended if the Identity Provider can provide them:

```text
Subject claim: NameID
Email claim: email
Username claim: username
Display name claim: displayName
Groups claim: groups
```

ADFS often uses URI-style claims:

```text
Email claim:
http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress

Username claim:
http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn

Display name claim:
http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name

Groups claim:
http://schemas.xmlsoap.org/claims/Group
```

If possible, configure ADFS to issue short claim names:

```text
email
username
displayName
groups
```

---

## Login Policies

### Auto Create Users

If enabled, IncidentRelay automatically creates a local user on the first successful SSO login.

```text
Enabled: a new local user is created automatically.
Disabled: only users that already exist in IncidentRelay can log in.
```

---

### Auto Link by Email

If enabled, IncidentRelay can link an SSO identity to an existing local user by email.

```text
Enabled: an existing user with the same email is linked to the SSO identity.
Disabled: existing users are not linked automatically.
```

Enable this only when email addresses from the Identity Provider are trusted.

---

### Require Verified Email

If enabled, IncidentRelay requires a verified email from the OIDC provider.

OIDC providers usually expose this as:

```text
email_verified: true
```

If the Identity Provider does not send `email_verified`, leave this option disabled.

---

### Allowed Domains

Restricts SSO login to users with email addresses from specific domains.

Example:

```text
example.com
corp.example.com
```

If the list is empty, no domain restriction is applied.

---

## Group Mappings

Group mappings connect external Identity Provider groups to IncidentRelay groups.

Example:

```text
External group: IncidentRelay-Infra
IncidentRelay group: Infrastructure
Role: editor
```

When a user logs in through SSO and the Identity Provider sends the group `IncidentRelay-Infra`, IncidentRelay adds the user to the `Infrastructure` group with the `editor` role.

---

## Group Roles

Supported group roles:

| Role | Description |
|---|---|
| `viewer` | Can view group data. |
| `editor` | Can manage group objects. |
| `user_admin` | Can manage group users. |

Legacy roles `read_only` and `rw` are not used.

---

## Group Synchronization

### Sync Group Memberships

If enabled, IncidentRelay applies group mappings on every SSO login.

```text
Enabled: user group memberships are updated during login.
Disabled: SSO is used only for authentication, and groups are not synchronized.
```

---

### Remove Missing Group Memberships

If enabled, IncidentRelay disables group memberships that were previously added through SSO mapping but are no longer present in the claims from the Identity Provider.

```text
Enabled: strict synchronization.
Disabled: IncidentRelay only adds new memberships and does not remove missing ones.
```

For the first rollout, it is safer to leave this disabled.

---

## OIDC Setup

### 1. Create an OIDC Client in the Identity Provider

Use this redirect URI:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

Example:

```text
https://incidentrelay.example.com/api/auth/sso/keycloak/callback
```

### 2. Create an OIDC Provider in IncidentRelay

Minimum settings:

```text
Protocol: OIDC
Slug: keycloak
Label: Keycloak
Enabled: true
Client ID: <client_id>
Client Secret: <client_secret>
Issuer URL: https://keycloak.example.com/realms/<realm>
Scope: openid email profile
```

### 3. Configure Claims

Recommended values:

```text
Subject claim: sub
Email claim: email
Username claim: preferred_username
Display name claim: name
Groups claim: groups
```

### 4. Test Login

Open:

```text
https://incidentrelay.example.com/login
```

The SSO login button should be visible on the login page.

---

## SAML Setup

### 1. Create a SAML Provider in IncidentRelay

Minimum settings:

```text
Protocol: SAML
Slug: adfs
Label: ADFS
Enabled: true
```

SP URLs:

```text
SP Entity ID:
https://incidentrelay.example.com/api/auth/sso/adfs/metadata

ACS URL:
https://incidentrelay.example.com/api/auth/sso/adfs/callback

SLS URL:
https://incidentrelay.example.com/api/auth/sso/adfs/callback
```

Metadata URL to provide to the Identity Provider:

```text
https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

### 2. Configure the Identity Provider

On the ADFS / IdP side, configure:

```text
Relying party / SP Entity ID
ACS URL
NameID
Claims
```

### 3. Fill IdP Settings in IncidentRelay

```text
IdP Entity ID
IdP SSO URL
IdP SLO URL
IdP x509 certificate
```

### 4. Configure Claims

Example:

```text
Subject claim: NameID
Email claim: email
Username claim: username
Display name claim: displayName
Groups claim: groups
```

For ADFS, URI-style claims can be used if those are the claims actually sent by the Identity Provider.

---

## SAML Security

IncidentRelay supports SAML security settings per provider.

For the first setup, recommended settings are:

```text
Want assertions signed: true
Want messages signed: false
Sign AuthnRequest: false
Sign LogoutRequest: false
Sign LogoutResponse: false
Sign Metadata: false
Signature algorithm: RSA-SHA256
Digest algorithm: SHA256
```

If the Identity Provider requires signed AuthnRequests:

1. Generate an SP certificate and private key.
2. Upload the public certificate to the Identity Provider.
3. Fill these fields in IncidentRelay:
   - `SP x509 certificate`
   - `SP private key`
4. Enable:
   - `Sign AuthnRequest`

---

## ADFS: Common Questions

### Automatic Metadata Refresh

Current status:

```text
No
```

IncidentRelay does not automatically refresh ADFS metadata or certificates yet. The IdP x509 certificate must be configured manually.

If the ADFS certificate changes, update the `IdP x509 certificate` field in the SAML provider settings.

---

### Secure Hash Algorithm

Recommended value:

```text
SHA-256
```

SHA-1 is not recommended.

---

### Signature Verification Certificate

If ADFS does not require signed AuthnRequests:

```text
Not used. AuthnRequests are not signed.
```

If ADFS requires signed AuthnRequests, generate an SP certificate/private key and enable request signing in IncidentRelay.

---

### 2FA

2FA must be enforced on the ADFS / Identity Provider side.

IncidentRelay does not perform its own 2FA verification for SSO logins.

---

### Claims

Recommended claims:

```text
NameID
email
username
displayName
groups
```

---

## Secrets

Client Secret and SAML private key are stored encrypted.

IncidentRelay uses this setting for encryption:

```text
SSO_SECRET_ENCRYPTION_KEY
```

If this value is not configured, the main `SECRET_KEY` is used.

It is recommended to configure a separate persistent encryption key for SSO secrets.

Example:

```ini
[sso]
secret_encryption_key = change-me-to-a-long-random-secret
```

Important: if this key is changed after providers are saved, previously saved secrets cannot be decrypted.

---

## Public Base URL

A public IncidentRelay URL must be configured so callback and metadata URLs are generated correctly.

Example:

```ini
[app]
public_base_url = https://incidentrelay.example.com
```

If IncidentRelay is behind a reverse proxy, make sure the external URL uses the correct protocol, host, and port.

---

## Troubleshooting

### The SSO Button Is Not Visible on the Login Page

Check the public endpoint:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/providers
```

It should return an enabled provider:

```json
[
  {
    "enabled": true,
    "label": "ADFS",
    "protocol": "saml",
    "slug": "adfs"
  }
]
```

If the response is an empty list, check:

```text
provider enabled = true
provider deleted = false
```

---

### `/api/auth/sso/providers` Returns 401

Make sure SSO auth endpoints are available without authentication:

```text
/api/auth/sso/providers
/api/auth/sso/<slug>/login
/api/auth/sso/<slug>/callback
/api/auth/sso/<slug>/metadata
```

---

### The User Is Not Created After SSO Login

Check:

```text
Auto create users
```

If it is disabled, the user must already exist in IncidentRelay.

---

### Existing Users Are Not Linked to SSO

Check:

```text
Auto link by email
Email claim
Allowed domains
```

The email from the Identity Provider must match the local user email.

---

### Login Works but Groups Are Not Assigned

Check:

```text
Groups claim
Sync group memberships
Group mappings
```

Also make sure the Identity Provider actually sends groups in the SAML assertion or OIDC claims.

---

### SAML Login Fails After an ADFS Certificate Change

Update this field in the SAML provider settings:

```text
IdP x509 certificate
```
---

### Zitadel return sso_oidc_callback_failed

Update Authentication Method to Basic and generate clietn secret.

---

## Recommended First Rollout Settings

For the first SSO rollout:

```text
Auto create users: enabled
Auto link by email: enabled
Require verified email: disabled
Sync group memberships: enabled
Remove missing group memberships: disabled
Allowed domains: your corporate domain
```

After group mappings are verified, strict synchronization can be enabled:

```text
Remove missing group memberships: enabled
```

---

## Verification with curl

Public provider list:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/providers | jq
```

SAML metadata:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

OIDC/SAML login redirect:

```bash
curl -I https://incidentrelay.example.com/api/auth/sso/adfs/login
```
