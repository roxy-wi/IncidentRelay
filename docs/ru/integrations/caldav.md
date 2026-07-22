---
title: Синхронизация календарей CalDAV
description: Синхронизация расписаний дежурств команд IncidentRelay через CalDAV в режиме только для чтения.
---

# Синхронизация календарей CalDAV

IncidentRelay может предоставлять расписания дежурств (on-call) команд в виде календарей CalDAV, доступных только для чтения. Это удобно для календарных клиентов с прямой поддержкой CalDAV, таких как Apple Calendar, Thunderbird и DAVx5.

Каждая доступная команда предоставляется как отдельный календарь. Пользователи видят только календари тех команд, к которым им разрешён доступ на чтение.

## Когда использовать CalDAV

Используйте CalDAV, когда календарный клиент поддерживает учётные записи CalDAV и вы хотите автоматически обнаруживать все доступные календари команд.

Рекомендуемые клиенты:

| Клиент | Рекомендуемый способ |
|---|---|
| Apple Calendar на macOS | CalDAV |
| Apple Calendar на iOS/iPadOS | CalDAV |
| Thunderbird | CalDAV |
| DAVx5 на Android | CalDAV |
| Outlook | Вместо этого подписка ICS |
| Google Calendar | Вместо этого подписка ICS |

Для Outlook и Google Calendar используйте [ICS-ленты календарей](ics-calendar-feed.md).

## Требования

- IncidentRelay должен быть доступен по HTTPS из календарного клиента.
- У пользователя должен быть доступ хотя бы к одному календарю команды.
- Пользователь должен создать персональный API-токен с областью `calendar:read`.
- Пользователь должен использовать персональный API-токен в качестве пароля CalDAV.

Не используйте обычный пароль пользователя IncidentRelay для CalDAV.

## Создание API-токена для CalDAV

1. Откройте **Profile**.
2. Откройте вкладку **API tokens**.
3. Создайте новый токен.
4. Используйте понятное имя, например `caldav-calendar`.
5. Выберите область `calendar:read`.
6. Скопируйте сгенерированный токен.

Токен показывается только один раз. Если он потерян, отзовите его и создайте новый.

## URL-адрес CalDAV

Используйте базовый эндпоинт CalDAV:

```text
https://incidentrelay.example.com/caldav/
```

Замените `incidentrelay.example.com` на имя хоста вашего IncidentRelay.

Не используйте прямой путь к календарю команды при настройке учётной записи в Apple Calendar. Apple Calendar должен обнаруживать календари через корневой эндпоинт CalDAV.

## Apple Calendar на macOS

Откройте **Calendar → Add Account → Other CalDAV Account → Advanced**.

Используйте следующие значения:

```text
Account Type: Advanced
User Name: your IncidentRelay username or email
Password: personal API token with calendar:read
Server Address: incidentrelay.example.com
Server Path: /caldav/
Port: 443
Use SSL: enabled
```

Важно: поле **Server Address** должно содержать только имя хоста. Не включайте туда `https://`.

Правильно:

```text
incidentrelay.example.com
```

Неправильно:

```text
https://incidentrelay.example.com
```

## Apple Calendar на iOS или iPadOS

Откройте **Settings → Calendar → Accounts → Add Account → Other → Add CalDAV Account**.

Используйте:

```text
Server: incidentrelay.example.com
User Name: your IncidentRelay username or email
Password: personal API token with calendar:read
Description: IncidentRelay
```

Если клиент запрашивает расширенные настройки, используйте:

```text
Server Path: /caldav/
Port: 443
Use SSL: enabled
```

## Thunderbird

1. Откройте **Calendar**.
2. Выберите **New Calendar**.
3. Выберите **On the Network**.
4. Введите URL-адрес CalDAV:

```text
https://incidentrelay.example.com/caldav/
```

5. Используйте имя пользователя или email IncidentRelay.
6. Используйте персональный API-токен в качестве пароля.
7. Выберите календари команд, на которые вы хотите подписаться.

## DAVx5 на Android

1. Добавьте новую учётную запись в DAVx5.
2. Выберите вход по URL и имени пользователя.
3. Используйте:

```text
Base URL: https://incidentrelay.example.com/caldav/
User name: your IncidentRelay username or email
Password: personal API token with calendar:read
```

4. Выберите календари команд для синхронизации.

## Поведение в режиме только для чтения

Календари CalDAV в IncidentRelay доступны только для чтения.

Разрешённые операции:

```text
OPTIONS
PROPFIND
REPORT
GET
HEAD
PROPPATCH as no-op for client-side calendar metadata
```

Отклоняемые операции:

```text
PUT
DELETE
MKCALENDAR
```

Некоторые клиенты, особенно Apple Calendar, могут отправлять `PROPPATCH` для сохранения локальных свойств календаря, таких как цвет, отображаемое имя или порядок. IncidentRelay принимает эти запросы как no-op, чтобы обновление календаря в режиме только для чтения продолжало работать.

## Устранение неполадок

### Ошибка аутентификации

Проверьте, что:

- имя пользователя — это имя пользователя или email IncidentRelay;
- пароль — это персональный API-токен, а не пароль пользователя;
- у токена есть область `calendar:read`;
- токен не отозван и не истёк;
- пользователь активен.

Аутентификацию можно проверить с помощью curl:

```bash
curl -i \
  -u 'user@example.com:PERSONAL_API_TOKEN' \
  -X PROPFIND \
  -H 'Depth: 0' \
  https://incidentrelay.example.com/caldav/
```

Успешный ответ должен быть `207 Multi-Status`.

### Apple Calendar сообщает «No calendar home was specified»

Используйте корневой эндпоинт CalDAV в качестве пути сервера:

```text
/caldav/
```

Не используйте прямой путь к команде при настройке учётной записи.

### Apple Calendar сообщает, что доступ не разрешён

Проверьте в логах сервера ответы на `PROPPATCH` или `REPORT`. Apple Calendar ожидает успешных ответов WebDAV для некоторых операций с метаданными, даже если сам календарь доступен только для чтения.

Ожидаемое поведение:

```text
PROPPATCH /caldav/calendars/teams/<team_id>/ -> 207
REPORT    /caldav/calendars/teams/<team_id>/ -> 207
```

### Вход выполнен, но календари не появляются

Проверьте, что у пользователя есть доступ хотя бы к одной активной команде. Пользователю должно быть разрешено чтение календаря команды.

Также проверьте, что команда и её группа активны.

### События не появляются

Проверьте, что у команды есть ротации и будущие слоты дежурств. Команда без ротаций всё равно может быть обнаружена как пустой календарь.

Используйте curl для проверки домашнего каталога календарей:

```bash
curl -i \
  -u 'user@example.com:PERSONAL_API_TOKEN' \
  -X PROPFIND \
  -H 'Depth: 1' \
  https://incidentrelay.example.com/caldav/calendars/
```

Ответ должен содержать hrefs календарей, например:

```text
/caldav/calendars/teams/1/
```

## Заметки по безопасности

- CalDAV использует HTTP Basic Auth с персональным API-токеном.
- Области `calendar:read` достаточно для синхронизации календаря.
- Отзовите токен в разделе Profile, чтобы прекратить доступ по CalDAV.
- Не логируйте заголовок `Authorization`.
- Не публикуйте CalDAV по обычному HTTP в production.
- CalDAV не позволяет пользователям редактировать расписания IncidentRelay из внешних календарных клиентов.
