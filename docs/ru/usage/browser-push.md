---
title: Браузерные push-уведомления
description: PWA и браузерные push-уведомления на уровне профиля для назначенных пользователей.
---

# Браузерные push-уведомления

Браузерные push-уведомления позволяют пользователям получать алерты IncidentRelay прямо в браузере или установленном PWA.

Браузерные push-уведомления работают **на уровне профиля**, а не как канал уведомлений:

```text
User Profile -> Enable push on this device
Alert assigned to user -> Browser push to that user's active browser/PWA devices
```

Не создавайте канал уведомлений `browser_push` и не привязывайте браузерные push-уведомления к маршрутам. Если пользователь включает браузерные push-уведомления в профиле, IncidentRelay может автоматически отправлять уведомления об алертах на активные устройства (браузер/PWA) этого пользователя, когда алерт назначается на него.

## Требования

Для браузерных push-уведомлений необходимы:

- публичный HTTPS-URL для веб-интерфейса;
- работающий `/service-worker.js`, отдаваемый из корневой области видимости;
- настроенные на сервере публичный и приватный ключи VAPID;
- активная подписка на браузерные push-уведомления в профиле пользователя;
- алерт с установленным `assignee_id` на этого пользователя.

Для локального тестирования браузерным push-уведомлениям обычно требуется HTTPS, за исключением специфичных для браузера исключений для localhost.

## Настройка

Добавьте секцию браузерных push-уведомлений в основной конфиг IncidentRelay:

```ini
[browser_push]
enabled = true
vapid_public_key = CHANGE_ME_PUBLIC_KEY
vapid_private_key = /etc/incidentrelay/vapid/private_key.pem
vapid_subject = mailto:admin@example.com
action_token_ttl_seconds = 900
```

| Параметр | Описание |
|---|---|
| `enabled` | Включает или отключает браузерные push-уведомления глобально |
| `vapid_public_key` | Публичный ключ VAPID, возвращаемый браузеру для `PushManager.subscribe()` |
| `vapid_private_key` | Приватный ключ VAPID или путь к PEM-файлу, используемый сервером для отправки сообщений Web Push |
| `vapid_subject` | Контактный URI, включаемый в claims VAPID, обычно `mailto:admin@example.com` |
| `action_token_ttl_seconds` | Время жизни одноразовых токенов действий ACK/Resolve, встроенных в push-уведомления |

Перезапустите веб-сервис после изменения конфига. Перезапустите также планировщик, если уведомления об алертах в вашей установке отправляются процессом планировщика.

## Генерация ключей VAPID

Один из надёжных вариантов — сгенерировать приватный ключ в формате PEM и публичный ключ в формате base64url с помощью `py-vapid`:

```bash
mkdir -p /etc/incidentrelay/vapid

python3 - <<'PY'
from py_vapid import Vapid01
from py_vapid.utils import b64urlencode
from cryptography.hazmat.primitives import serialization

private_key_file = "/etc/incidentrelay/vapid/private_key.pem"

vapid = Vapid01()
vapid.generate_keys()
vapid.save_key(private_key_file)

public_key = b64urlencode(
    vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
)

if isinstance(public_key, bytes):
    public_key = public_key.decode("utf-8")

print("vapid_public_key = " + public_key)
print("vapid_private_key = " + private_key_file)
PY

chown -R incidentrelay:incidentrelay /etc/incidentrelay/vapid
chmod 700 /etc/incidentrelay/vapid
chmod 600 /etc/incidentrelay/vapid/private_key.pem
```

Используйте выведенные значения в секции конфига `[browser_push]`.

## Настройка пользователем

Откройте:

```text
Profile
```

Затем используйте блок браузерных push-уведомлений:

1. Введите имя устройства, например `Work laptop` или `Android phone`.
2. Нажмите `Enable push on this device`.
3. Разрешите уведомления в запросе браузера.
4. Нажмите `Send test push`.

На странице профиля перечислены активные устройства с браузерными push-уведомлениями. Пользователи могут отключить старые устройства на той же странице.

## Поведение при доставке алертов

Браузерные push-уведомления отправляются только назначенному пользователю:

```text
alert.assignee_id -> active browser push subscriptions for that user
```

Маршруту не нужен канал браузерных push-уведомлений. Обычные каналы уведомлений по-прежнему используют привязки «маршрут — канал», но браузерные push-уведомления автоматически проверяются для назначенного пользователя.

Если тестовое push-уведомление работает, а реальный алерт — нет, проверьте, что:

1. У алерта есть ответственный.
2. Ответственный — тот же пользователь, который включил push-уведомления в профиле.
3. Браузерные push-уведомления включены в конфиге.
4. Подписка включена и не удалена.
5. В браузере пользователя используется актуальный service worker.

Браузерные push-уведомления считаются доступной целью доставки для напоминаний и эскалаций, когда у назначенного пользователя есть активные push-подписки.

## Кнопки ACK и Resolve

Push-уведомления об алертах могут включать действия `Acknowledge` и `Resolve`. Эти кнопки используют короткоживущие одноразовые токены действий, встроенные в полезную нагрузку уведомления.

Эндпоинт действий намеренно сделан публичным:

```text
POST /api/push/actions
```

Он не требует персонального API-токена или cookie входа. Одноразовый токен действия аутентифицирует push-действие.

Время жизни токена по умолчанию:

```text
900 seconds
```

Измените его с помощью:

```ini
[browser_push]
action_token_ttl_seconds = 900
```

`token_expired` означает, что токен действия старше `action_token_ttl_seconds`. `token_already_used` означает, что токен действия того же уведомления уже был использован.

## Звук и вибрация уведомлений

IncidentRelay не настраивает пользовательский аудиофайл для браузерных push-уведомлений. Браузер и операционная система используют поведение уведомлений по умолчанию, когда уведомления разрешены и устройство не находится в беззвучном режиме или режиме «Не беспокоить».

Полезная нагрузка push-уведомлений не должна устанавливать `silent: true` для уведомлений об алертах. Мобильные браузеры, поддерживающие вибрацию, могут использовать шаблон вибрации уведомления, если он доступен.

## Обновления service worker

Service worker должен отдаваться по адресу:

```text
/service-worker.js
```

Рекомендуемые заголовки:

```text
Cache-Control: no-cache, no-store, must-revalidate
Service-Worker-Allowed: /
```

При изменении `service-worker.js` увеличьте версию кэша PWA/service worker, чтобы браузеры подхватили новую логику клика/действий по уведомлению.

## Эндпоинты API

Аутентифицированные эндпоинты профиля:

```text
GET    /api/profile/push/vapid-public-key
GET    /api/profile/push/subscriptions
POST   /api/profile/push/subscriptions
DELETE /api/profile/push/subscriptions/{subscription_id}
POST   /api/profile/push/test
```

Публичный эндпоинт одноразовых действий:

```text
POST /api/push/actions
```

## Устранение неполадок

### Браузерные push-уведомления отключены или не настроен публичный ключ VAPID

Проверьте:

```text
GET /api/profile/push/vapid-public-key
```

Ожидаемый ответ:

```json
{
  "enabled": true,
  "public_key": "B..."
}
```

Если `enabled` равно false или `public_key` равно null, исправьте конфиг `[browser_push]` и перезапустите сервис.

### Тестовое push-уведомление работает, а реальные алерты — нет

Тестовое push-уведомление отправляется текущему пользователю профиля. Реальное push-уведомление об алерте отправляется на `alert.assignee_id`.

Проверьте последние алерты:

```sql
select id, status, assignee_id, route_id, last_notification_at
from alert
order by id desc
limit 5;
```

Затем проверьте подписки:

```sql
select id, user_id, device_name, enabled, deleted, last_seen_at
from browser_push_subscription
order by id desc;
```

`user_id` подписки должен совпадать с `assignee_id` алерта.

### Push-действие возвращает token_expired

Одноразовый токен действия был старше `action_token_ttl_seconds` в момент, когда браузер отправил действие.

### Push-действие возвращает token_already_used

Тот же токен действия ACK/Resolve уже был использован. Это может произойти после двойного клика, повторной попытки браузера или если пользователь нажал одно и то же действие уведомления более одного раза.
