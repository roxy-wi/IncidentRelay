---
title: Канал Slack
description: Настройка входящего вебхука Slack и уведомлений через Bot API.
---

# Канал Slack

Slack — это исходящий канал уведомлений.

IncidentRelay поддерживает два режима доставки в Slack:

1. Режим входящего вебхука для односторонних уведомлений.
2. Режим Bot API с интерактивными кнопками `Acknowledge` и `Resolve` и обновлением сообщений.

Интерактивные действия Bot API можно получать двумя способами:

- через HTTP Request URL с signing secret;
- через Socket Mode по исходящему WebSocket-соединению с токеном уровня приложения (app-level token).

Режим Bot API рекомендуется, когда ответственные должны управлять алертами прямо из Slack.

## Режим входящего вебхука

Используйте этот режим, когда вам нужно только отправлять уведомления.

Создайте входящий вебхук в Slack и настройте канал с параметрами:

```json
{
  "mode": "webhook",
  "webhook_url": "https://hooks.slack.com/services/..."
}
```

Сообщения входящего вебхука не могут обновляться IncidentRelay после того, как алерт подтверждён или разрешён.

## Режим Bot API

Режим Bot API поддерживает:

- отправку уведомлений об алертах с помощью Block Kit;
- кнопки `Acknowledge` и `Resolve`;
- обновление исходного сообщения Slack после ACK или разрешения;
- удаление действий после разрешения алерта;
- опциональную атрибуцию пользователю IncidentRelay.

Конфигурация HTTP-действий:

```json
{
  "mode": "bot_api",
  "connection_mode": "http",
  "bot_token": "xoxb-...",
  "channel_id": "C0123456789",
  "signing_secret": "..."
}
```

Конфигурация Socket Mode:

```json
{
  "mode": "bot_api",
  "connection_mode": "socket_mode",
  "bot_token": "xoxb-...",
  "app_token": "xapp-...",
  "channel_id": "C0123456789"
}
```

## Создание приложения Slack

1. Откройте страницу управления приложениями Slack.
2. Создайте новое приложение для целевого рабочего пространства.
3. Откройте **OAuth & Permissions**.
4. Добавьте scope токена бота:

   ```text
   chat:write
   ```

5. Установите или переустановите приложение в рабочем пространстве.
6. Скопируйте **Bot User OAuth Token**. Обычно он начинается с `xoxb-`.
7. Пригласите бота в канал Slack, который будет получать алерты IncidentRelay.

IncidentRelay использует `chat.postMessage` для отправки сообщений и `chat.update` для обновления существующих сообщений.

## Выбор транспорта интерактивных действий

### HTTP Request URL

Используйте режим HTTP, когда Slack может обращаться к IncidentRelay по публичному HTTPS.


Откройте **Interactivity & Shortcuts** в настройках приложения Slack и включите интерактивность.

Укажите Request URL:

```text
https://incidentrelay.example.com/api/integrations/slack/actions
```

Замените `https://incidentrelay.example.com` на настроенный публичный URL IncidentRelay.

IncidentRelay проверяет каждое взаимодействие, используя:

- `X-Slack-Signature`;
- `X-Slack-Request-Timestamp`;
- signing secret приложения Slack.

Запросы старше пяти минут отклоняются.

## Поиск signing secret

Откройте **Basic Information** в настройках приложения Slack и найдите **App Credentials**.

Скопируйте **Signing Secret** в конфигурацию канала Slack в IncidentRelay.

Не используйте старый verification token Slack. IncidentRelay проверяет подписанные запросы с помощью signing secret.

## Socket Mode

Socket Mode рекомендуется для приватных сетей, установок за NAT и с ограничениями межсетевого экрана. IncidentRelay открывает исходящее WebSocket-соединение к Slack, поэтому для кнопок действий не требуется публичный Request URL или `public_base_url`.

В настройках приложения Slack:

1. Откройте **Settings → Socket Mode** и включите Socket Mode.
2. Откройте **Basic Information → App-Level Tokens**.
3. Сгенерируйте токен со scope `connections:write`.
4. Скопируйте токен, начинающийся с `xapp-`.
5. Оставьте **Interactivity & Shortcuts** включённым; в Socket Mode Request URL не требуется.

В IncidentRelay выберите **Bot API → Socket Mode** и введите токен бота, токен уровня приложения и ID канала Slack.

Воркер Slack должен быть запущен. Docker Compose включает `incidentrelay-slack`. Для systemd:

```bash
sudo cp etc/systemd/incidentrelay-slack-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now incidentrelay-slack-worker
```

Проверка статуса:

```bash
systemctl status incidentrelay-slack-worker
journalctl -u incidentrelay-slack-worker -f
```

Одно соединение Socket Mode открывается для каждого отдельного токена уровня приложения. Несколько каналов Slack в IncidentRelay могут использовать одно и то же приложение Slack и токен уровня приложения.

## Поиск ID канала

Откройте целевой канал Slack и скопируйте его ID канала.

Используйте ID, например:

```text
C0123456789
```

Не вводите отображаемое имя канала.

Бот должен иметь возможность публиковать сообщения в настроенном канале.

## Настройка IncidentRelay

В IncidentRelay:

1. Откройте **Channels**.
2. Создайте или отредактируйте канал Slack.
3. Выберите **Bot API**.
4. Введите токен бота и ID канала.
5. Выберите способ подключения интерактивных действий:
   - **HTTP Request URL** и введите Signing Secret; либо
   - **Socket Mode** и введите App-Level Token.
6. Сохраните канал.
7. Привяжите канал к нужному маршруту.
8. Отправьте тестовое уведомление или реальный тестовый алерт.

Для интерактивных HTTP-действий настройте `public_base_url` и убедитесь, что Slack может обращаться к `POST /api/integrations/slack/actions` по HTTPS. Socket Mode не требует, чтобы этот эндпоинт был публично доступен.

## Атрибуция пользователю

Пользователь IncidentRelay может иметь ID пользователя Slack в своём профиле.

Когда ответственный нажимает `Acknowledge` или `Resolve`, IncidentRelay считывает ID пользователя Slack из полезной нагрузки взаимодействия и пытается сопоставить его с активным пользователем IncidentRelay.

Если соответствующего пользователя нет, действие всё равно может быть обработано, но не будет отнесено к локальному пользователю.

## Поведение сообщений

Для активного алерта сообщение Slack содержит:

- заголовок и описание алерта;
- статус, важность и приоритет;
- команду, сервис и назначенного ответственного;
- ссылки на сервис и runbook, когда они настроены;
- ссылку на алерт в IncidentRelay;
- кнопки `Acknowledge` и `Resolve`.

После подтверждения:

- исходное сообщение обновляется;
- статус меняется на acknowledged;
- кнопка `Acknowledge` удаляется;
- кнопка `Resolve` остаётся.

После разрешения:

- исходное сообщение обновляется;
- статус меняется на resolved;
- все кнопки действий удаляются.

Режим входящего вебхука только отправляет сообщения и не поддерживает эти обновления.

## Кнопка теста

Тест канала проверяет, что IncidentRelay может отправить сообщение, используя настроенные учётные данные Slack.

Он не подтверждает, что:

- канал привязан к правильному маршруту;
- матчеры маршрута принимают реальный алерт;
- фильтры важности пропускают алерт;
- Slack может обращаться к эндпоинту интерактивных действий.

Используйте реальный тестовый алерт для проверки полного рабочего процесса.

## Устранение неполадок

### Slack возвращает `invalid_auth`

Проверьте, что:

- токен начинается с `xoxb-`;
- приложение установлено в правильном рабочем пространстве;
- токен не был отозван;
- приложение было переустановлено после изменения scope.

### Slack возвращает `not_in_channel`

Пригласите бота в настроенный канал Slack.

### Сообщения отправляются, но кнопки не работают

Проверьте, что:

- выбран режим Bot API;
- интерактивность включена в приложении Slack;
- Request URL указан правильно;
- `public_base_url` указан правильно;
- эндпоинт IncidentRelay публично доступен по HTTPS;
- signing secret совпадает с приложением Slack;
- обратные прокси сохраняют тело запроса и заголовки подписи Slack.

### Действие Slack отклоняется как устаревшее

Запросы взаимодействий Slack старше пяти минут отклоняются.

Проверьте синхронизацию системного времени на сервере IncidentRelay и обратном прокси.

### Действие Slack отклоняется из-за несоответствия канала

ID канала Slack во взаимодействии должен совпадать с ID канала, настроенным в IncidentRelay.

Проверьте, что уведомление было отправлено в ожидаемый канал Slack и что конфигурация канала IncidentRelay не была изменена.

### Сообщения не обновляются

Обновление сообщений требует режима Bot API.

Проверьте, что при исходной доставке были сохранены оба значения:

- ID канала Slack;
- временная метка сообщения Slack.

Доставки через входящий вебхук не могут обновляться.

## Замечания по безопасности

- Держите токен бота и signing secret в тайне.
- Не включайте ни одно из этих значений в журналы, скриншоты или обращения в поддержку.
- Ротируйте токен бота и signing secret, если они были раскрыты.
- Открывайте наружу только необходимые HTTPS-эндпоинты IncidentRelay.
- Держите время сервера синхронизированным, чтобы проверка временных меток работала корректно.

## Справочные материалы Slack

- [Проверка запросов от Slack](https://api.slack.com/authentication/verifying-requests-from-slack)
- [Обработка взаимодействий](https://api.slack.com/interactivity/handling)
- [chat.postMessage](https://api.slack.com/methods/chat.postMessage)
- [chat.update](https://api.slack.com/methods/chat.update)
- [Входящие вебхуки](https://api.slack.com/messaging/webhooks)

### У воркера Socket Mode нет соединений

Проверьте, что:

- канал Slack включён;
- `connection_mode` равен `socket_mode`;
- токен приложения начинается с `xapp-`;
- у токена приложения есть `connections:write`;
- Socket Mode включён в приложении Slack;
- служба или контейнер воркера Slack запущены;
- разрешены исходящие HTTPS- и WebSocket-соединения к Slack.

## Журналирование воркера Slack

Воркер Socket Mode использует роль журналирования `slack` и пишет JSON-логи в отдельный файл. Настройте путь в `incidentrelay.conf`:

```ini
[logging]
slack_worker_file = /var/log/incidentrelay/incidentrelay-slack-worker.log
```

Файл содержит события `oncall.slack`, `oncall.slack.socket` и события уровня воркера `oncall.error`. Штатное правило logrotate уже покрывает этот файл через `/var/log/incidentrelay/*.log`.

Для установок systemd:

```bash
tail -f /var/log/incidentrelay/incidentrelay-slack-worker.log
journalctl -u incidentrelay-slack-worker -f
```

Для Docker Compose:

```bash
docker compose exec incidentrelay-slack \
  tail -f /var/log/incidentrelay/incidentrelay-slack-worker.log
```
