---
title: Настройка
description: Справочник по файлу конфигурации IncidentRelay
---

# Настройка

IncidentRelay читает путь к файлу конфигурации из:

```text
INCIDENTRELAY_CONFIG_FILE
```

Пример:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Для systemd:

```ini
Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Для Docker Compose:

```yaml
environment:
  INCIDENTRELAY_CONFIG_FILE: /etc/incidentrelay/incidentrelay.conf
```

Старое имя `ONCALL_CONFIG_FILE` использовать не следует.

## Переопределение через переменные окружения

Любой параметр из файла конфигурации можно также задать переменной окружения
`INCIDENTRELAY__<SECTION>__<OPTION>`, где секция и параметр записываются в
верхнем регистре. Переменная имеет приоритет над файлом:

```bash
export INCIDENTRELAY__DATABASE__PASSWORD=replace-with-the-database-password
export INCIDENTRELAY__LOGGING__LEVEL=DEBUG
```

Чтобы прочитать значение из файла, добавьте к имени `__FILE` и укажите путь.
Так можно использовать секреты Docker и Kubernetes или тома Secrets Store CSI,
не записывая секреты в `incidentrelay.conf`:

```bash
export INCIDENTRELAY__DATABASE__PASSWORD__FILE=/run/secrets/db-password
```

Перевод строки в конце файла игнорируется. Задавать одновременно переменную и
её форму `__FILE` нельзя — это ошибка. Для systemd поместите переменные в
`EnvironmentFile=`.

Если `main.secret_key` задан через переменную окружения, пустые
`main.secret_encryption_key`, `auth.jwt_secret`, `mattermost.action_secret` и
`voice.callback_secret` берут его значение, а не генерируются Docker entrypoint.

`main.secret_encryption_key` шифрует секреты, которые хранятся в базе, поэтому
менять его после первого запуска нельзя — неважно, задан он в файле
конфигурации, в переменной окружения или через `__FILE`. Если он пустой,
IncidentRelay шифрует ключом `main.secret_key`, и тогда то же самое относится к
нему. Если ключ шифрования изменился, Docker entrypoint не запустит сервис:
верните прежний ключ. Сменить ключ напрямую нельзя. Entrypoint сравнивает ключ с
хэшем (с солью), который хранит в `/var/lib/incidentrelay`, поэтому проверка
работает, только если этот каталог сохраняется между перезапусками.

В `[voice_provider]`, где набор параметров зависит от провайдера, переменная
только переопределяет параметр, который есть в файле, и имя параметра
сохраняет написание из файла. Новых параметров переменные туда не добавляют:

```ini
[voice_provider]
apiKey =
```

```bash
export INCIDENTRELAY__VOICE_PROVIDER__APIKEY=replace-with-the-api-key
```

Параметры провайдера также могут ссылаться на переменную напрямую, например
`api_token = ${VOICE_API_TOKEN}`, см.
[Настройка голосового провайдера](../voice-providers/configuration.md).

## Основной секрет и секрет аутентификации

Сгенерируйте два разных случайных значения и не меняйте их при перезапусках и
обновлениях:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

```ini
[main]
secret_key = замените-на-первое-случайное-значение

[auth]
jwt_secret = замените-на-второе-случайное-значение
jwt_cookie_secure = true
```

Параметр `secret_key` относится к секции `[main]`, а не `[server]`.
Параметр `jwt_secret` относится к `[auth]`. Не используйте одно значение для
обоих параметров. При HTTPS в `public_base_url` установите
`jwt_cookie_secure = true`.

## Секция server

```ini
[server]
host = 0.0.0.0
port = 8080
public_base_url = https://incidentrelay.example.com
```

| Параметр | Описание |
|---|---|
| `host` | Адрес, к которому привязывается веб-сервис |
| `port` | HTTP-порт |
| `public_base_url` | Внешний URL, используемый в ссылках алертов, кнопках и колбэках |

В продакшене `public_base_url` должен быть реальным внешним HTTPS-URL.

## База данных: SQLite

```ini
[database]
type = sqlite
name = /var/lib/incidentrelay/incidentrelay.db

[sqlite]
wal = true
busy_timeout = 5000
```

SQLite подходит для небольших self-hosted инсталляций. При использовании SQLite оставляйте один веб-воркер.

## База данных: PostgreSQL

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

Используйте PostgreSQL для более крупных инсталляций, высокого объёма алертов, нескольких веб-воркеров или долгосрочных продакшен-развёртываний.

## Политика исходящих HTTP-подключений

IncidentRelay защищает исходящие HTTP-запросы к адресам, заданным
администратором, от SSRF. По умолчанию запрещены private, loopback, link-local,
multicast, reserved и unspecified адреса назначения.

Политика задаётся в секции `[security]`:

```ini
[security]
outbound_private_network_allowlist =
outbound_http_max_redirects = 3
outbound_http_max_response_bytes = 1048576
```

`outbound_private_network_allowlist` — список IPv4/IPv6-адресов и CIDR-сетей,
разделённых запятыми или точками с запятой. Эти адреса явно разрешаются для
исходящих запросов, даже если они относятся к private или другим обычно
запрещённым диапазонам.

Примеры:

```ini
# Только один внутренний сервис.
outbound_private_network_allowlist = 192.168.50.10/32
```

```ini
# Несколько разрешённых внутренних сетей/адресов.
outbound_private_network_allowlist = 10.20.0.0/16,192.168.50.10/32,fd00:1234::/48
```

Отдельный IP можно указать и без длины префикса, однако `/32` для IPv4 и `/128`
для IPv6 явно показывают область разрешения. Используйте максимально узкие
диапазоны вместо разрешения всей private-сети.

Эта политика используется общим клиентом исходящих HTTP-запросов, в том числе
при загрузке OIDC metadata и JWKS, а также для исходящих интеграций:
generic/Teams/Discord webhooks, Slack webhooks и запросов к Mattermost API.
Это не allowlist имён хостов: IncidentRelay сначала разрешает DNS-имя, затем
проверяет полученные IP-адреса.

Для DNS-имени **каждый адрес, возвращённый DNS, должен быть публичным или явно
разрешённым**. Если хотя бы один адрес запрещён, запрос блокируется целиком.
Целевой адрес каждого redirect разрешается через DNS и проверяется повторно.

!!! warning "Влияние обновления на 2.1"
    В IncidentRelay 2.1 эта политика применяется к исходящим запросам.
    Поэтому после обновления с 1.2 существующий внутренний OIDC metadata/JWKS
    endpoint или исходящая интеграция может перестать работать, даже если URL
    не менялся. До обновления разрешите внутренние endpoints с хоста/pod
    IncidentRelay и добавьте только необходимые IP или CIDR.

Например, если внутренний identity provider разрешается в `10.42.7.15`:

```ini
[security]
outbound_private_network_allowlist = 10.42.7.15/32
```

После изменения настройки перезапустите все процессы IncidentRelay, которые
могут выполнять исходящие запросы.

Allowlist меняет только сетевую политику назначения. Он **не** отключает
проверку HTTPS-сертификата и не добавляет доверие к приватному центру
сертификации. Для внутренних HTTPS endpoints с private CA этот CA также должен
быть установлен в trust store операционной системы или контейнера.

## Trace обработки алертов

Глобальный уровень детализации Explain Trace задаётся в `[alerts]`:

```ini
[alerts]
explain_trace_level = full
```

Поддерживаются `full`, `compact` и `disabled`. `full` сохраняет текущее подробное поведение. `compact` сохраняет последовательность шагов обработки, но не записывает `input_summary`, payload результата и `data` отдельных шагов. `disabled` вообще не создаёт строки Alert Explain Trace. Глобальное правило Event Orchestration может переопределить значение для совпавших событий действием `set_trace_level`.

## История событий алерта

Историю входящих событий дочерних алертов можно настраивать независимо от самого lifecycle:

```ini
[alerts]
event_history = full
```

Поддерживаются `full`, `initial` и `disabled`. `full` сохраняет входящие события `created`, `updated` и `resolved` дочерних алертов. `initial` сохраняет только первое событие `created`. `disabled` не сохраняет эти входящие history-записи. При этом обновление состояния алерта, grouping, notifications, escalation и resolution продолжают работать во всех режимах. Operational timeline — acknowledgement, comments, reminders, maintenance, correlations, responders и stakeholders — сохраняется всегда.

Global и Service Event Orchestration могут переопределить значение для совпавших событий действием `set_alert_event_history`. Если несколько совпавших actions задают уровень, применяется последнее действие.


## Scheduler для Alert Shelving

Временные shelves AlertGroup завершаются scheduler-процессом:

```ini
[alerts]
shelve_lifecycle_check_interval_seconds = 30
shelve_lifecycle_batch_size = 100
```

`check_interval_seconds` задаёт частоту обработки истёкших shelves, а `batch_size` ограничивает один проход. Scheduler должен быть запущен, если используется timed shelving. Shelving приостанавливает notifications, reminders и escalation, но не меняет технический status AlertGroup и service/business impact. Подробнее: [Shelving](../usage/shelving.md).

## Политика хранения данных

В IncidentRelay 2.1 все новые retention-настройки находятся в одной секции:

```ini
[retention]
alert_days = 30
# explain_trace_days = 30
# orchestration_execution_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

`alert_days = 0` используется по умолчанию и хранит завершённую историю alerts бессрочно. Explain Trace и обычные Event Orchestration executions наследуют `alert_days`, если для них не задан отдельный override. Точные правила удаления и совместимость при обновлении описаны в разделе [Политика хранения данных](../administration/data-retention.md).

## Секция SMTP

Каналы уведомлений по email используют глобальные настройки SMTP. Транспорт SMTP не настраивается отдельно для каждого канала.

```ini
[smtp]
host = 127.0.0.1
port = 25
from = incidentrelay@example.com
use_tls = false
user =
password =
```

Для локального ретранслятора без аутентификации оставьте `user` и `password` пустыми.

Для SMTP-сервера с аутентификацией:

```ini
[smtp]
host = smtp.example.com
port = 587
from = incidentrelay@example.com
use_tls = true
user = incidentrelay@example.com
password = change-me
```

Уведомления по email отправляются на адрес email из профиля назначенного пользователя.

## Прокси для Telegram

Если окружение требует прокси для вызовов Telegram Bot API, настройте его глобально. Значения токенов держите в конфигурации канала, а не в глобальной конфигурации.

Имена параметров в примерах зависят от текущей реализации конфигурации сервиса. Используйте один и тот же файл конфигурации для веб-процессов и процессов Telegram-воркера.

## Секция voice

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret = change-me
```

| Параметр | Описание |
|---|---|
| `provider` | Имя голосового провайдера |
| `providers_dir` | Каталог с модулями пользовательских провайдеров |
| `callback_secret` | Секрет, используемый для проверки колбэков |

Уведомления голосовым вызовом отправляются на номер телефона из профиля назначенного пользователя.

## Секция browser push

Браузерные push-уведомления — это уведомления уровня профиля для PWA/браузера. Они не настраиваются как каналы уведомлений.

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
| `action_token_ttl_seconds` | Время жизни одноразовых токенов ACK/Resolve/Shelve/Unshelve, встраиваемых в push-уведомления |

После изменения настроек браузерных push-уведомлений перезапустите веб-сервис. Перезапустите также планировщик, если в вашей инсталляции он отправляет уведомления.

Подробнее: [Браузерные push-уведомления](../usage/browser-push.md).

## Секция metrics

IncidentRelay может отдавать метрики Prometheus по `GET /metrics`:

```ini
[metrics]
enabled = true
auth_token = replace-with-a-random-value
```

| Параметр | Описание |
|---|---|
| `enabled` | Отдает `GET /metrics` в текстовом формате Prometheus. По умолчанию `false`, endpoint отвечает 404 |
| `auth_token` | Если задан, запросы должны передавать `Authorization: Bearer <token>`, иначе возвращается 401 |

Endpoint отключен по умолчанию. Включайте его, только когда метрики кто-то собирает, и закрывайте порт на сетевом уровне так же, как для `/healthz`.

Значение для `auth_token` можно получить командой `openssl rand -hex 32`. Пример настройки сбора в Prometheus:

```yaml
scrape_configs:
  - job_name: web
    scheme: https
    metrics_path: /metrics
    bearer_token_file: /etc/prometheus/incidentrelay.token
    static_configs:
      - targets:
          - incidentrelay.example.com
```

Метрики:

| Метрика | Тип | Описание |
|---|---|---|
| `incidentrelay_http_requests_total` | counter | Обработанные HTTP-запросы, метки `method` и `status` |
| `incidentrelay_http_request_duration_seconds` | histogram | Задержка обработки запросов, метка `method` |
| `incidentrelay_database_up` | gauge | 1, если база ответила на `SELECT 1` в момент сбора, иначе 0 |
| `incidentrelay_migrations_pending` | gauge | Число файлов миграций, которые еще не применены; отсутствует, пока состояние миграций неизвестно |
| `incidentrelay_build_info` | gauge | Версия запущенного сервиса, метка `version`, значение всегда 1 |
| `incidentrelay_alerts_received_total` | counter | Алерты, принятые через integration API, метка `source` |
| `incidentrelay_alert_group_actions_total` | counter | Переходы групп алертов, метка `action`: `created`, `acknowledged`, `resolved`, `reopened` |
| `incidentrelay_user_notification_deliveries_recent` | gauge | Доставки пользовательских уведомлений, обновленные за последние 24 часа, метки `method` и `status` |
| `incidentrelay_alert_notification_errors_recent` | gauge | Доставки уведомлений алертов, завершившиеся ошибкой, обновленные за последние 24 часа, метка `provider` |
| `incidentrelay_scheduler_last_run_timestamp_seconds` | gauge | Unix-время последнего heartbeat планировщика, `0`, если он еще не запускался |
| `incidentrelay_worker_last_seen_timestamp_seconds` | gauge | Последний успешный heartbeat цикла worker; метка `worker`: `scheduler`, `telegram`, `slack` |
| `incidentrelay_user_notification_queue_depth` | gauge | Пользовательские уведомления, уже ожидающие обработки или находящиеся в обработке; метка `state`: `due`, `processing` |
| `incidentrelay_user_notification_queue_oldest_age_seconds` | gauge | Возраст самого старого элемента очереди пользовательских уведомлений; метка `state`: `due`, `processing` |
| `incidentrelay_orchestration_pending_events` | gauge | Отложенные события оркестрации; метка `status`: `pending`, `activating`, `failed` |
| `incidentrelay_orchestration_oldest_due_age_seconds` | gauge | Возраст самого старого отложенного события, для которого уже наступило время активации/retry |

`incidentrelay_database_up` и `incidentrelay_migrations_pending` вычисляются в момент сбора и повторяют проверки `/readyz`. `/metrics` продолжает отвечать, когда база данных недоступна, поэтому обе метрики остаются видимыми во время сбоя. Пока состояние миграций прочитать нельзя (база недоступна или проверка не выполнилась), сэмпл `incidentrelay_migrations_pending` отсутствует, а не равен `0` — метрика отдается только тогда, когда ее значение действительно известно. Заведите алерт на `incidentrelay_database_up = 0` и не полагайтесь только на число отложенных миграций.

Подсчет запросов активен только при `enabled = true`. После изменения настроек metrics перезапустите веб-сервис, а также планировщик и воркеры — они подхватывают настройку при старте. `/metrics` отдает только веб-сервис; планировщик и остальные воркеры только записывают в него события.

Обычно IncidentRelay работает несколькими процессами за одной точкой сбора: несколько Gunicorn-воркеров плюс отдельные демоны планировщика и Telegram/Slack-воркеров. Чтобы один сбор `/metrics` покрывал их все, каждый процесс IncidentRelay записывает свои счетчики в один общий каталог, заданный переменной окружения `PROMETHEUS_MULTIPROC_DIR`, а веб-воркеры при сборе объединяют файлы всех процессов. В готовых поставках это уже настроено: systemd-юниты используют общий каталог `/run/incidentrelay/metrics`, поэтому сбор покрывает все юниты хоста — веб-воркеры, планировщик и чат-воркеры. Без переменной — одиночный процесс в development-запуске — счетчики покрывают только этот один процесс.

Файлы счетчиков привязаны к PID процессов, поэтому каталог `PROMETHEUS_MULTIPROC_DIR` можно разделять только процессам, которые видят одни и те же PID: на одном хосте или внутри одного контейнера. Никогда не указывайте контейнерам один и тот же каталог — независимые PID-пространства могут переиспользовать одни и те же PID и портить файлы друг друга. Поэтому Docker-образ дает каждому сервисному контейнеру собственный каталог внутри `/var/lib/incidentrelay/metrics/`; сбор `/metrics` в контейнерной поставке агрегирует воркеров веб-контейнера, а переходы от планировщика и чат-воркеров попадают в их собственные каталоги и в нем не видны. Чтобы объединить их, понадобился бы механизм агрегации через границы контейнеров, которого в этой функциональности нет.

Если указываете свой путь в `PROMETHEUS_MULTIPROC_DIR`, оставьте его процессам одного хоста или одного контейнера; каталог должен существовать и быть доступен для записи до старта процессов, при выключенном `[metrics]` каталог вообще не затрагивается, так что нерабочий каталог никогда не блокирует выключенное развертывание. Файлы live-гаугов завершившихся процессов удаляются при запуске следующего процесса IncidentRelay. Файлы счетчиков и гистограмм умерших процессов намеренно сохраняются: удаление одного из них уменьшает объединенный счетчик на долю умершего процесса, а Prometheus читает это как сброс счетчика и искажает `rate()` и `increase()`. Устаревшие файлы счетчиков продолжают участвовать в агрегации, пока каталог не будет очищен при полном передеплое; их количество ограничено числом разных PID, которые каталог когда-либо видел. Очистка гаугов определяет живость по PID, поэтому переиспользованный PID сохраняет файл гауга умершего процесса, пока не завершится процесс, который теперь владеет этим PID.

Гаужи, считаемые из базы (`incidentrelay_database_up`, `incidentrelay_migrations_pending`, `incidentrelay_user_notification_deliveries_recent`, `incidentrelay_alert_notification_errors_recent`, `incidentrelay_scheduler_last_run_timestamp_seconds`, `incidentrelay_build_info`), вычисляются один раз за сбор, поэтому их значения не зависят от числа процессов.

`incidentrelay_user_notification_deliveries_recent`, `incidentrelay_alert_notification_errors_recent` и `incidentrelay_scheduler_last_run_timestamp_seconds` пересчитываются из базы в момент сбора, поэтому работают между процессами. Обе метрики доставок учитывают строки, обновленные за последние 24 часа: строки доставок меняются на месте (pending переходит в sent или failed, приходят новые ошибки провайдеров), поэтому окно идет по `updated_at`, а не по `created_at`, и сбор никогда не сканирует всю историю доставок. Когда база недоступна, они исчезают из выдачи, а heartbeat равен `0`; причину показывает `incidentrelay_database_up = 0`. Для heartbeat нужен работающий воркер планировщика; сама heartbeat-job запускается только при включенном `[metrics]`.

`incidentrelay_worker_last_seen_timestamp_seconds` хранится в БД, поэтому работает между systemd-сервисами и отдельными Docker/Kubernetes-контейнерами. Scheduler также остается доступен под совместимым именем `incidentrelay_scheduler_last_run_timestamp_seconds`. Telegram и Slack обновляют timestamp после успешной итерации worker; alert следует настраивать только для тех worker, которые действительно запущены в deployment.

Гейджи очереди пользовательских уведомлений показывают текущий backlog, а не историю. `state="due"` считает только `pending`-доставки, у которых уже наступил `scheduled_at`, поэтому намеренно отложенные уведомления не выглядят зависшими. `state="processing"` считает захваченные доставки, а возраст измеряется от последнего обновления состояния.

`incidentrelay_orchestration_pending_events` показывает текущее состояние отложенных событий. `failed` означает, что автоматические попытки активации исчерпаны и событие требует внимания. `incidentrelay_orchestration_oldest_due_age_seconds` учитывает только `pending`-события, у которых уже наступило время активации/retry; будущие pause-события возраст не увеличивают.

## Настройки планировщика

Процесс планировщика проверяет напоминания, эскалации и периодические задания.

Планировщик обновляет heartbeat каждые `heartbeat_interval_seconds` (по умолчанию `30`, секция `[scheduler]`); метрика `incidentrelay_scheduler_last_run_timestamp_seconds` в `/metrics` показывает, как давно он запускался.

Интервал пробуждения планировщика отличается от интервалов напоминаний ротаций. Интервалы напоминаний ротаций настраиваются для каждой ротации отдельно:

```text
0 disables reminders for that rotation
>= 60 sends reminders at that interval in seconds
1..59 invalid
```

Не используйте глобальную настройку reminder-after как запасной вариант во время выполнения, когда ротации требуют явного интервала.

## Журналирование

Если включено журналирование в файл, используйте путь с правами на запись:

```ini
[main]
log_level = INFO
log_file = /var/log/incidentrelay/incidentrelay.log
```

Для systemd и контейнеров проверяйте также журнал или логи контейнера.
