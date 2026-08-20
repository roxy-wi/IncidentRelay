---
title: Установка в Kubernetes
description: Развёртывание IncidentRelay в Kubernetes с помощью включённого Helm-чарта
---

# Установка в Kubernetes

Helm-чарт находится в репозитории в каталоге `helm/incidentrelay`. Он развёртывает веб-приложение и фоновые воркеры, формирует конфигурацию приложения в Secret и подключает пробы `/healthz` и `/readyz` к Kubernetes.

Чарт пока не опубликован в репозитории чартов. Устанавливайте его из локальной копии этого репозитория.

## Требования

```text
Kubernetes 1.23+
Helm 3
StorageClass, если используется стандартная конфигурация SQLite
```

## Что развёртывает чарт

```text
Deployment  <release>-web        приложение Gunicorn + Flask
Deployment  <release>-scheduler  напоминания, эскалации, периодические задания
Deployment  <release>-telegram   воркер обратных вызовов Telegram (необязательно)
Deployment  <release>-slack      воркер Slack Socket Mode (необязательно)
Service     <release>            ClusterIP на порту 8080
Secret      <release>-config     сформированный incidentrelay.conf
PersistentVolumeClaim <release>-data   /var/lib/incidentrelay
ServiceAccount и Ingress, если он включён
```

Все компоненты используют один образ и выбираются переменной `INCIDENTRELAY_SERVICE` — точно так же, как при установке через Docker Compose.

## Быстрый старт

```bash
helm install incidentrelay ./helm/incidentrelay \
  --set-string config.main.secret_key="$(openssl rand -hex 32)"
```

Чарт загружает `ghcr.io/roxy-wi/incidentrelay` и по умолчанию использует тег из `appVersion` чарта. Чтобы зафиксировать конкретный образ:

```bash
helm upgrade --install incidentrelay ./helm/incidentrelay \
  --set image.repository=ghcr.io/roxy-wi/incidentrelay \
  --set image.tag=2.1 \
  --set-string config.main.secret_key="$(openssl rand -hex 32)"
```

Следите за развёртыванием:

```bash
kubectl get pods -l app.kubernetes.io/instance=incidentrelay -w
```

## Конфигурация

IncidentRelay читает все настройки из одного INI-файла, смонтированного по пути `/etc/incidentrelay/incidentrelay.conf`. Чарт формирует этот файл из объекта `config` в `values.yaml`: ключи верхнего уровня становятся разделами INI, а вложенные ключи — параметрами.

```yaml
config:
  main:
    secret_key: ""
  auth:
    api_auth_required: true
    rbac_enforced: true
    jwt_secret: ""
  server:
    host: 0.0.0.0
    port: 8080
    public_base_url: https://incidentrelay.example.com
```

превращается в:

```ini
[main]
secret_key =

[auth]
api_auth_required = true
rbac_enforced = true
jwt_secret = <общий secret, если значение оставлено пустым в values.yaml>

[server]
host = 0.0.0.0
port = 8080
public_base_url = https://incidentrelay.example.com
```

Таким способом можно задать всё, что допустимо в `incidentrelay.conf`. Список доступных параметров см. в разделе [Конфигурация](configuration.md).

Укажите в `public_base_url` адрес, по которому пользователи действительно открывают приложение. Он используется в создаваемых ссылках и обратных вызовах.

При конфигурации, создаваемой самим чартом, `config.main.secret_key` обязателен. В IncidentRelay 2.0 он используется как общий fallback для `main.secret_encryption_key`, `auth.jwt_secret`, `mattermost.action_secret` и `voice.callback_secret`, если соответствующие значения оставлены пустыми. Это нужно, чтобы все pod'ы использовали стабильные общие ключи, особенно при PostgreSQL, когда `/var/lib/incidentrelay` не является общим томом. При необходимости каждый из этих секретов можно задать отдельным случайным значением.

### Собственный Secret

Сформированный файл содержит учётные данные, поэтому чарт хранит его в Secret. Если вы хотите управлять Secret самостоятельно, создайте его, поместив полную конфигурацию в ключ `incidentrelay.conf`, и укажите его в чарте:

```bash
kubectl create secret generic incidentrelay-config \
  --from-file=incidentrelay.conf=./incidentrelay.conf
```

```yaml
existingConfigSecret: incidentrelay-config
```

Когда задан `existingConfigSecret`, объект `config` игнорируется, а чарт не создаёт собственный Secret.

!!! note "Примечание"
    Чарт добавляет к pod'ам аннотацию `checksum/config`, чтобы при изменении конфигурации они перезапускались автоматически. При использовании `existingConfigSecret` чарт не видит его содержимое, поэтому аннотация не добавляется — после изменения Secret перезапустите pod'ы самостоятельно.

## База данных

### SQLite (по умолчанию)

SQLite работает без дополнительной настройки. Все компоненты монтируют один PersistentVolumeClaim в `/var/lib/incidentrelay`.

```yaml
persistence:
  enabled: true
  accessModes:
    - ReadWriteOnce
  size: 1Gi
  storageClass: ""
```

!!! warning "Предупреждение"
    SQLite поддерживается только при `persistence.enabled=true` и `web.replicaCount=1`. Для конфигурации SQLite, создаваемой самим чартом, чарт автоматически добавляет обязательный pod affinity для scheduler/Telegram/Slack, чтобы они запускались на том же узле, что и web pod, и монтировали один ReadWriteOnce claim. SQLite на сетевом ReadWriteMany-хранилище (например NFS) всё равно использовать нельзя. Для многоузловой или горизонтально масштабируемой конфигурации используйте PostgreSQL.

PVC создаётся чартом и поэтому удаляется командой `helm uninstall`. Чтобы сохранить данные, создайте claim самостоятельно и укажите ссылку на него:

```yaml
persistence:
  existingClaim: incidentrelay-data
```

### PostgreSQL

Для production-нагрузки подключите чарт к PostgreSQL и отключите постоянное хранилище:

```yaml
config:
  database:
    type: postgresql
    host: postgres.example.svc
    port: 5432
    name: incidentrelay
    user: incidentrelay
    password: <database-password>

persistence:
  enabled: false
```

## Миграции и масштабирование веб-компонента

По умолчанию веб-pod запускает миграции в entrypoint перед запуском Gunicorn:

```yaml
web:
  runMigrations: true
  replicaCount: 1
```

Пока этот параметр включён, оставьте `replicaCount` равным `1`: несколько одновременно запускающихся pod'ов будут конкурировать при выполнении миграций. Чтобы запустить более одной реплики веб-компонента, отключите этот параметр и выполняйте миграции отдельно:

```bash
kubectl exec deploy/incidentrelay-web -- python manage.py migrate
```

```yaml
web:
  runMigrations: false
  replicaCount: 3
  strategy:
    type: RollingUpdate
```

`RollingUpdate` подходит только для PostgreSQL. При использовании общего тома SQLite оставьте стандартную стратегию `Recreate`: она не позволяет старому и новому pod'ам одновременно записывать один файл базы данных во время развёртывания.

## Пробы состояния

Веб-deployment использует следующие эндпоинты проб без аутентификации:

```text
/healthz  liveness   возвращает 200, пока процесс обслуживает запросы; не обращается к базе данных
/readyz   readiness  возвращает 200, только если база данных доступна и все миграции применены
```

Startup-проба даёт первому запуску до пяти минут — этого достаточно для выполнения миграций на новой базе данных.

## Доступ

По умолчанию Service имеет тип `ClusterIP`. Для быстрой проверки:

```bash
kubectl port-forward svc/incidentrelay 8080:8080
```

```text
http://127.0.0.1:8080/login
```

Для постоянного доступа включите Ingress:

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
  hosts:
    - host: incidentrelay.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - incidentrelay.example.com
      secretName: incidentrelay-tls
```

Значение `config.server.public_base_url` должно соответствовать хосту Ingress.

## Создание первого администратора

```bash
kubectl exec -it deploy/incidentrelay-web -- \
  python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Перед использованием в production смените пароль, затем перейдите к разделу [Первый вход и настройка](first-login.md).

## Воркеры

Планировщик обрабатывает ротации, напоминания и эскалации. Без него напоминания и эскалации вообще не работают:

```yaml
scheduler:
  enabled: true
```

Воркер Telegram обрабатывает кнопки обратных вызовов. Если бот не настроен, воркер безвредно простаивает:

```yaml
telegram:
  enabled: true
```

Воркер Slack поддерживает WebSocket-соединение Socket Mode, через которое работают интерактивные кнопки `Acknowledge` и `Resolve`. Сами сообщения Slack отправляет веб-компонент, поэтому без этого воркера уведомления продолжат поступать — не будут работать только кнопки:

```yaml
slack:
  enabled: true
```

Без настроенного канала Slack воркер простаивает. Он самостоятельно получает конфигурацию канала из базы данных, поэтому после добавления канала перезапускать pod не нужно. Для Socket Mode не требуется публичный Request URL, поэтому этот режим обычно выбирают для кластеров, не доступных из интернета. Настройка приложения Slack описана в разделе [Slack](../integrations/slack.md).

Для каждого компонента доступны обычные параметры размещения и ресурсов:

```yaml
scheduler:
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
  nodeSelector: {}
  tolerations: []
  affinity: {}
  extraEnv: []
```

## Логи

Приложение записывает JSON-логи в файлы в каталоге `/var/log/incidentrelay`, а не в стандартный вывод, поэтому `kubectl logs` показывает только сообщение entrypoint. Читайте файлы напрямую:

```bash
kubectl exec deploy/incidentrelay-web -- tail -f /var/log/incidentrelay/incidentrelay.log
kubectl exec deploy/incidentrelay-scheduler -- tail -f /var/log/incidentrelay/incidentrelay-scheduler.log
```

Для логов используется том `emptyDir`, поэтому после перезапуска pod'а файлы не сохраняются. Структура файлов описана в разделе [Логирование](../administration/logging.md).

## Пользовательские голосовые провайдеры

Подключите плагины провайдеров ко всем компонентам с помощью общих дополнительных томов:

```yaml
extraVolumes:
  - name: voice-providers
    configMap:
      name: incidentrelay-voice-providers

extraVolumeMounts:
  - name: voice-providers
    mountPath: /usr/local/lib/incidentrelay/voice_providers
    readOnly: true
```

## Обновление и удаление

### Обновление с 1.x до 2.0

Чарт 2.0 умеет повторно использовать values от 1.x. При рендеринге он добавляет новые безопасные настройки авторизации и общие JWT/encryption/callback secrets до формирования `incidentrelay.conf`, поэтому старые values не приводят к генерации разных runtime-ключей в разных pod'ах. `config.main.secret_key` при этом должен быть задан уникальным случайным значением.

При использовании `existingConfigSecret` Helm не может нормализовать внешний файл. До обновления на 2.0 убедитесь, что в нём задан корректный `main.secret_key`, включены нужные настройки `[auth]` и используется стабильный `auth.jwt_secret` (либо параметр отсутствует/пустой и приложение использует `main.secret_key`).

Для SQLite оставьте `persistence.enabled=true` и `web.replicaCount=1`. Для PostgreSQL и многоузловой установки можно установить `persistence.enabled=false`, когда все security secrets уже стабильно заданы в сгенерированной или внешней конфигурации.

```bash
helm upgrade incidentrelay ./helm/incidentrelay --reuse-values
```

```bash
helm uninstall incidentrelay
```

Команда `helm uninstall` также удаляет созданный чартом PersistentVolumeClaim, а вместе с ним и базу данных SQLite. Используйте `persistence.existingClaim`, если данные должны сохраняться после удаления релиза.
