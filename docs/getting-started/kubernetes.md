---
title: Kubernetes Installation
description: Deploy IncidentRelay to Kubernetes with the bundled Helm chart
---

# Kubernetes Installation

A Helm chart is bundled with the repository in `helm/incidentrelay`. It deploys the web application and the background workers, renders the application config into a Secret, and wires the `/healthz` and `/readyz` probes to Kubernetes.

The chart is not published to a chart repository yet. Install it from a checkout of this repository.

## Requirements

```text
Kubernetes 1.23+
Helm 3
a StorageClass, if you keep the default SQLite setup
```

## What the chart deploys

```text
Deployment  <release>-web        Gunicorn + Flask application
Deployment  <release>-scheduler  reminders, escalations, periodic jobs
Deployment  <release>-telegram   Telegram callback worker (optional)
Deployment  <release>-slack      Slack Socket Mode worker (optional)
Service     <release>            ClusterIP on port 8080
Secret      <release>-config     rendered incidentrelay.conf
PersistentVolumeClaim <release>-data   /var/lib/incidentrelay
ServiceAccount, and an Ingress when enabled
```

Each component runs the same image and is selected by `INCIDENTRELAY_SERVICE`, exactly as in the Docker Compose setup.

## Quick start

```bash
helm install incidentrelay ./helm/incidentrelay \
  --set-string config.main.secret_key="$(openssl rand -hex 32)"
```

The chart pulls `ghcr.io/roxy-wi/incidentrelay` and defaults the tag to the chart `appVersion`. To pin an explicit image:

```bash
helm upgrade --install incidentrelay ./helm/incidentrelay \
  --set image.repository=ghcr.io/roxy-wi/incidentrelay \
  --set image.tag=2.0 \
  --set-string config.main.secret_key="$(openssl rand -hex 32)"
```

Watch the rollout:

```bash
kubectl get pods -l app.kubernetes.io/instance=incidentrelay -w
```

## Configuration

IncidentRelay reads every setting from a single INI file mounted at `/etc/incidentrelay/incidentrelay.conf`. The chart renders that file from the `config` map in `values.yaml`: top-level keys become INI sections, nested keys become options.

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

becomes:

```ini
[main]
secret_key =

[auth]
api_auth_required = true
rbac_enforced = true
jwt_secret = <same shared secret when left empty in values.yaml>

[server]
host = 0.0.0.0
port = 8080
public_base_url = https://incidentrelay.example.com
```

Anything valid in `incidentrelay.conf` can be set this way. See [Configuration](configuration.md) for the available options.

Set `public_base_url` to the address users actually reach. It is used for generated links and callbacks.

For chart-rendered configuration, `config.main.secret_key` is required. IncidentRelay 2.0 uses it as the shared fallback for `main.secret_encryption_key`, `auth.jwt_secret`, `mattermost.action_secret`, and `voice.callback_secret` when those values are empty. This is intentional: every pod must use stable shared signing/encryption keys, especially when PostgreSQL is used and `/var/lib/incidentrelay` is not shared. You can override any of those values with a separate random secret.

### Bring your own Secret

The rendered file carries credentials, so the chart stores it in a Secret. To manage that Secret yourself instead, create one with the whole config under the key `incidentrelay.conf` and point the chart at it:

```bash
kubectl create secret generic incidentrelay-config \
  --from-file=incidentrelay.conf=./incidentrelay.conf
```

```yaml
existingConfigSecret: incidentrelay-config
```

When `existingConfigSecret` is set, the `config` map is ignored and the chart renders no Secret of its own.

!!! note
    The chart adds a `checksum/config` pod annotation so config changes restart the pods automatically. With `existingConfigSecret` the chart cannot see the content, so the annotation is omitted — restart the pods yourself after changing the Secret.

## Database

### SQLite (default)

SQLite works out of the box. All components mount one PersistentVolumeClaim for `/var/lib/incidentrelay`.

```yaml
persistence:
  enabled: true
  accessModes:
    - ReadWriteOnce
  size: 1Gi
  storageClass: ""
```

!!! warning
    SQLite is supported only with `persistence.enabled=true` and `web.replicaCount=1`. For chart-rendered SQLite configuration, the chart automatically adds required pod affinity to scheduler/Telegram/Slack workers so they run on the web pod's node and can mount the same ReadWriteOnce claim. SQLite over network-backed ReadWriteMany storage such as NFS is still unsafe. For anything multi-node or horizontally scaled, use PostgreSQL.

The PVC is created by the chart and therefore removed by `helm uninstall`. To keep the data, create the claim yourself and reference it:

```yaml
persistence:
  existingClaim: incidentrelay-data
```

### PostgreSQL

For production, point the chart at PostgreSQL and turn persistence off:

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

## Migrations and scaling the web component

By default the web pod runs migrations in its entrypoint before Gunicorn starts:

```yaml
web:
  runMigrations: true
  replicaCount: 1
```

Keep `replicaCount` at `1` while this is on — several pods starting at once would race on the migrations. To run more than one web replica, disable it and migrate out of band:

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

`RollingUpdate` is only appropriate with PostgreSQL. On the shared SQLite volume keep the default `Recreate`, which prevents the old and new pod from writing one database file during a rollout.

## Health probes

The web deployment is wired to the unauthenticated probe endpoints:

```text
/healthz  liveness   200 as long as the process serves requests; does not touch the database
/readyz   readiness  200 only when the database is reachable and all migrations are applied
```

A startup probe allows up to five minutes for the first boot, which covers migrations on a fresh database.

## Access

By default the Service is `ClusterIP`. For a quick look:

```bash
kubectl port-forward svc/incidentrelay 8080:8080
```

```text
http://127.0.0.1:8080/login
```

For permanent access, enable the Ingress:

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

Keep `config.server.public_base_url` in sync with the Ingress host.

## Create the first admin user

```bash
kubectl exec -it deploy/incidentrelay-web -- \
  python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Change the password before production use, then continue with [First Login and Setup](first-login.md).

## Workers

The scheduler evaluates rotations, reminders and escalations. It is required for reminders and escalations to work at all:

```yaml
scheduler:
  enabled: true
```

The Telegram worker processes callback buttons. It idles harmlessly without a configured bot:

```yaml
telegram:
  enabled: true
```

The Slack worker holds the Socket Mode WebSocket that carries interactive `Acknowledge` and `Resolve` buttons. Slack messages themselves are sent by the web component, so without this worker notifications still arrive — only their buttons do nothing:

```yaml
slack:
  enabled: true
```

It idles without a configured Slack channel, and picks up channel configuration from the database on its own, so no pod restart is needed after adding one. Socket Mode needs no public Request URL, which makes it the usual choice for clusters that are not exposed to the internet. See [Slack](../integrations/slack.md) for the Slack app setup.

Each component accepts the usual placement and sizing knobs:

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

## Logs

The application writes JSON logs to files under `/var/log/incidentrelay`, not to standard output, so `kubectl logs` shows only the entrypoint banner. Read the files directly:

```bash
kubectl exec deploy/incidentrelay-web -- tail -f /var/log/incidentrelay/incidentrelay.log
kubectl exec deploy/incidentrelay-scheduler -- tail -f /var/log/incidentrelay/incidentrelay-scheduler.log
```

The log volume is an `emptyDir`, so these files do not survive a pod restart. See [Logging](../administration/logging.md) for the file layout.

## Custom voice providers

Mount provider plugins into every component with the shared extra volumes:

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

## Upgrade and uninstall

### Upgrading from 1.x to 2.0

The 2.0 chart can reuse 1.x values. During rendering it materializes the new secure auth defaults and shared JWT/encryption/callback secrets before creating `incidentrelay.conf`, so old values do not cause different pods to generate different runtime keys. `config.main.secret_key` must still be present and must be a unique random value.

If you use `existingConfigSecret`, Helm cannot normalize that external file. Before the 2.0 upgrade, make sure it contains a valid `main.secret_key`, enables the desired `[auth]` settings, and uses a stable `auth.jwt_secret` (or omits/leaves it empty so the application falls back to `main.secret_key`).

For SQLite, keep `persistence.enabled=true` and `web.replicaCount=1`. For PostgreSQL/multi-node deployments, set `persistence.enabled=false` once every security secret is stable in the rendered or external config.

```bash
helm upgrade incidentrelay ./helm/incidentrelay --reuse-values
```

```bash
helm uninstall incidentrelay
```

`helm uninstall` also deletes the PersistentVolumeClaim created by the chart, and with it the SQLite database. Use `persistence.existingClaim` if you need the data to outlive the release.
