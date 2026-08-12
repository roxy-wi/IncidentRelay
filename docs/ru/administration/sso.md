---
title: SSO
description: Настройка единого входа OIDC и SAML в IncidentRelay.
---

# SSO

IncidentRelay поддерживает аутентификацию через внешние поставщики удостоверений (Identity Provider) с использованием:

- OIDC
- SAML 2.0

Поставщики SSO настраиваются в административном UI:

```text
Admin → SSO
```

Страница доступна только администраторам IncidentRelay.

---

## Как работает SSO

1. Администратор создаёт поставщика SSO.
2. Пользователь открывает страницу входа IncidentRelay.
3. Если поставщик включён, на `/login` появляется кнопка входа через SSO.
4. Пользователь перенаправляется к внешнему поставщику удостоверений.
5. После успешной аутентификации поставщик удостоверений перенаправляет пользователя обратно в IncidentRelay.
6. IncidentRelay читает утверждения (claims) пользователя и находит, связывает или создаёт локального пользователя.
7. Если включена синхронизация групп, IncidentRelay применяет сопоставления групп.

---

## Поддерживаемые протоколы

### OIDC

OIDC можно использовать с Keycloak, Authentik, Zitadel, Dex, Azure AD / Entra ID и другими OIDC-совместимыми поставщиками.

Типовые настройки OIDC:

```text
Issuer URL
Client ID
Client Secret
Scopes
Redirect URI
```

URL колбэка IncidentRelay:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

Пример для slug поставщика `keycloak`:

```text
https://incidentrelay.example.com/api/auth/sso/keycloak/callback
```

---

### SAML 2.0

SAML можно использовать с ADFS, Keycloak SAML, Okta SAML, Authentik SAML и другими поставщиками удостоверений SAML.

Типовые настройки SAML:

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

ACS URL IncidentRelay:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

URL метаданных SAML IncidentRelay:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/metadata
```

Пример для slug поставщика `adfs`:

```text
https://incidentrelay.example.com/api/auth/sso/adfs/callback
https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

---

## Настройки поставщика

### Основные поля

| Поле | Описание |
|---|---|
| `Slug` | Уникальное имя поставщика. Используется в URL. Пример: `keycloak`, `adfs`, `corp-sso`. |
| `Label` | Человекочитаемое имя поставщика. Отображается на странице входа. |
| `Protocol` | `oidc` или `saml`. |
| `Enabled` | Если отключено, поставщик не отображается на странице входа. |

---

## Утверждения (Claims)

IncidentRelay использует утверждения (claims), чтобы связать внешнюю личность пользователя с локальным пользователем IncidentRelay.

Рекомендуемые утверждения:

```text
subject / NameID
email
username
displayName
groups
mobile
```

### Поля утверждений в IncidentRelay

| Поле | Назначение                                                            |
|---|--------------------------------------------------------------------|
| `Subject claim` | Стабильный уникальный идентификатор пользователя из внешнего поставщика удостоверений. |
| `Email claim` | Адрес электронной почты пользователя.                                                |
| `Username claim` | Логин или имя пользователя.                                            |
| `Display name claim` | Отображаемое имя пользователя.                                                 |
| `Groups claim` | Список внешних групп, назначенных пользователю.                      |
| `Phone claim` | Номер телефона пользователя.                                                 |

---

## Рекомендуемые утверждения OIDC

Для большинства поставщиков OIDC используйте:

```text
Subject claim: sub
Email claim: email
Username claim: preferred_username
Display name claim: name
Groups claim: groups
```

Некоторые поставщики удостоверений используют другое утверждение для групп:

```text
groups
roles
realm_access.roles
resource_access.<client_id>.roles
```

Если поставщик возвращает вложенные утверждения, используйте полный путь через точку.

Пример:

```text
Groups claim: realm_access.roles
```

---

## Рекомендуемые утверждения SAML / ADFS

Для SAML рекомендуются короткие имена утверждений, если поставщик удостоверений может их предоставить:

```text
Subject claim: NameID
Email claim: email
Username claim: username
Display name claim: displayName
Groups claim: groups
```

ADFS часто использует утверждения в стиле URI:

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

По возможности настройте ADFS на выдачу коротких имён утверждений:

```text
email
username
displayName
groups
```

---

## Политики входа

### Автоматическое создание пользователей

Если включено, IncidentRelay автоматически создаёт локального пользователя при первом успешном входе через SSO.

```text
Enabled: a new local user is created automatically.
Disabled: only users that already exist in IncidentRelay can log in.
```

---

### Автоматическая привязка по email

Если включено, IncidentRelay может связать личность SSO с существующим локальным пользователем по email.

```text
Enabled: an existing user with the same email is linked to the SSO identity.
Disabled: existing users are not linked automatically.
```

Включайте это только тогда, когда адресам электронной почты от поставщика удостоверений можно доверять.

---

### Требовать подтверждённый email

Если включено, IncidentRelay требует подтверждённый email от поставщика OIDC.

Поставщики OIDC обычно предоставляют это как:

```text
email_verified: true
```

Если поставщик удостоверений не отправляет `email_verified`, оставьте эту опцию отключённой.

---

### Разрешённые домены

Ограничивает вход через SSO пользователями с адресами электронной почты из определённых доменов.

Пример:

```text
example.com
corp.example.com
```

Если список пуст, ограничение по домену не применяется.

---

## Сопоставления групп

Сопоставления групп связывают группы внешнего поставщика удостоверений с группами IncidentRelay.

Пример:

```text
External group: IncidentRelay-Infra
IncidentRelay group: Infrastructure
Role: editor
```

Когда пользователь входит через SSO и поставщик удостоверений отправляет группу `IncidentRelay-Infra`, IncidentRelay добавляет пользователя в группу `Infrastructure` с ролью `editor`.

---

## Роли групп

Поддерживаемые роли групп:

| Роль | Описание |
|---|---|
| `viewer` | Может просматривать данные группы. |
| `editor` | Может управлять объектами группы. |
| `user_admin` | Может управлять пользователями группы. |

Устаревшие роли `read_only` и `rw` не используются.

---

## Синхронизация групп

### Синхронизация членства в группах

Если включено, IncidentRelay применяет сопоставления групп при каждом входе через SSO.

```text
Enabled: user group memberships are updated during login.
Disabled: SSO is used only for authentication, and groups are not synchronized.
```

---

### Удаление отсутствующих членств в группах

Если включено, IncidentRelay отключает членства в группах, которые ранее были добавлены через сопоставление SSO, но больше не присутствуют в утверждениях от поставщика удостоверений.

```text
Enabled: strict synchronization.
Disabled: IncidentRelay only adds new memberships and does not remove missing ones.
```

Для первого развёртывания безопаснее оставить это отключённым.

---

## Настройка OIDC

### 1. Создайте клиента OIDC в поставщике удостоверений

Используйте этот redirect URI:

```text
https://incidentrelay.example.com/api/auth/sso/<provider_slug>/callback
```

Пример:

```text
https://incidentrelay.example.com/api/auth/sso/keycloak/callback
```

### 2. Создайте поставщика OIDC в IncidentRelay

Минимальные настройки:

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

### 3. Настройте утверждения

Рекомендуемые значения:

```text
Subject claim: sub
Email claim: email
Username claim: preferred_username
Display name claim: name
Groups claim: groups
```

### 4. Проверьте вход

Откройте:

```text
https://incidentrelay.example.com/login
```

Кнопка входа через SSO должна быть видна на странице входа.

---

## Настройка SAML

### 1. Создайте поставщика SAML в IncidentRelay

Минимальные настройки:

```text
Protocol: SAML
Slug: adfs
Label: ADFS
Enabled: true
```

URL SP:

```text
SP Entity ID:
https://incidentrelay.example.com/api/auth/sso/adfs/metadata

ACS URL:
https://incidentrelay.example.com/api/auth/sso/adfs/callback

SLS URL:
https://incidentrelay.example.com/api/auth/sso/adfs/callback
```

URL метаданных для передачи поставщику удостоверений:

```text
https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

### 2. Настройте поставщика удостоверений

На стороне ADFS / IdP настройте:

```text
Relying party / SP Entity ID
ACS URL
NameID
Claims
```

### 3. Заполните настройки IdP в IncidentRelay

```text
IdP Entity ID
IdP SSO URL
IdP SLO URL
IdP x509 certificate
```

### 4. Настройте утверждения

Пример:

```text
Subject claim: NameID
Email claim: email
Username claim: username
Display name claim: displayName
Groups claim: groups
```

Для ADFS можно использовать утверждения в стиле URI, если именно эти утверждения фактически отправляет поставщик удостоверений.

---

## Безопасность SAML

IncidentRelay поддерживает настройки безопасности SAML для каждого поставщика.

Для первой настройки рекомендуются следующие параметры:

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

Если поставщик удостоверений требует подписанных AuthnRequest:

1. Сгенерируйте сертификат SP и закрытый ключ.
2. Загрузите открытый сертификат в поставщик удостоверений.
3. Заполните эти поля в IncidentRelay:
   - `SP x509 certificate`
   - `SP private key`
4. Включите:
   - `Sign AuthnRequest`

---

## ADFS: частые вопросы

### Автоматическое обновление метаданных

Текущий статус:

```text
No
```

IncidentRelay пока не обновляет метаданные или сертификаты ADFS автоматически. Сертификат IdP x509 необходимо настраивать вручную.

Если сертификат ADFS меняется, обновите поле `IdP x509 certificate` в настройках поставщика SAML.

---

### Алгоритм безопасного хеширования

Рекомендуемое значение:

```text
SHA-256
```

SHA-1 не рекомендуется.

---

### Сертификат проверки подписи

Если ADFS не требует подписанных AuthnRequest:

```text
Not used. AuthnRequests are not signed.
```

Если ADFS требует подписанных AuthnRequest, сгенерируйте сертификат/закрытый ключ SP и включите подписание запросов в IncidentRelay.

---

### 2FA

2FA должна принудительно применяться на стороне ADFS / поставщика удостоверений.

IncidentRelay не выполняет собственную проверку 2FA для входов через SSO.

---

### Утверждения

Рекомендуемые утверждения:

```text
NameID
email
username
displayName
groups
```

---

## Секреты

Client Secret и закрытый ключ SAML хранятся в зашифрованном виде.

IncidentRelay использует эту настройку для шифрования:

```text
SSO_SECRET_ENCRYPTION_KEY
```

Если это значение не настроено, используется основной `SECRET_KEY`.

Рекомендуется настроить отдельный постоянный ключ шифрования для секретов SSO.

Пример:

```ini
[sso]
secret_encryption_key = change-me-to-a-long-random-secret
```

Важно: если этот ключ изменить после сохранения поставщиков, ранее сохранённые секреты не удастся расшифровать.

---

## Публичный базовый URL

Публичный URL IncidentRelay должен быть настроен, чтобы URL колбэков и метаданных генерировались корректно.

Пример:

```ini
[app]
public_base_url = https://incidentrelay.example.com
```

Если IncidentRelay находится за обратным прокси, убедитесь, что внешний URL использует правильный протокол, хост и порт.

---

## Устранение неполадок

### Кнопка SSO не видна на странице входа

Проверьте публичный эндпоинт:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/providers
```

Он должен вернуть включённого поставщика:

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

Если ответ — пустой список, проверьте:

```text
provider enabled = true
provider deleted = false
```

---

### `/api/auth/sso/providers` возвращает 401

Убедитесь, что эндпоинты аутентификации SSO доступны без аутентификации:

```text
/api/auth/sso/providers
/api/auth/sso/<slug>/login
/api/auth/sso/<slug>/callback
/api/auth/sso/<slug>/metadata
```

---

### Пользователь не создаётся после входа через SSO

Проверьте:

```text
Auto create users
```

Если это отключено, пользователь должен уже существовать в IncidentRelay.

---

### Существующие пользователи не связываются с SSO

Проверьте:

```text
Auto link by email
Email claim
Allowed domains
```

Email от поставщика удостоверений должен совпадать с email локального пользователя.

---

### Вход работает, но группы не назначаются

Проверьте:

```text
Groups claim
Sync group memberships
Group mappings
```

Также убедитесь, что поставщик удостоверений действительно отправляет группы в утверждении SAML или в утверждениях OIDC.

---

### Вход через SAML не работает после смены сертификата ADFS

Обновите это поле в настройках поставщика SAML:

```text
IdP x509 certificate
```
---

### Zitadel возвращает sso_oidc_callback_failed

Измените Authentication Method на Basic и сгенерируйте client secret.

---

## Рекомендуемые настройки первого развёртывания

Для первого развёртывания SSO:

```text
Auto create users: enabled
Auto link by email: enabled
Require verified email: disabled
Sync group memberships: enabled
Remove missing group memberships: disabled
Allowed domains: your corporate domain
```

После проверки сопоставлений групп можно включить строгую синхронизацию:

```text
Remove missing group memberships: enabled
```

---

## Проверка с помощью curl

Публичный список поставщиков:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/providers | jq
```

Метаданные SAML:

```bash
curl -s https://incidentrelay.example.com/api/auth/sso/adfs/metadata
```

Перенаправление входа OIDC/SAML:

```bash
curl -I https://incidentrelay.example.com/api/auth/sso/adfs/login
```
