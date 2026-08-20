{{/*
Expand the name of the chart.
*/}}
{{- define "incidentrelay.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name (63 char limit).
*/}}
{{- define "incidentrelay.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart name and version for the chart label.
*/}}
{{- define "incidentrelay.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "incidentrelay.labels" -}}
helm.sh/chart: {{ include "incidentrelay.chart" . }}
{{ include "incidentrelay.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "incidentrelay.selectorLabels" -}}
app.kubernetes.io/name: {{ include "incidentrelay.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Service account name.
*/}}
{{- define "incidentrelay.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "incidentrelay.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image reference.
*/}}
{{- define "incidentrelay.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{/*
Name of the Secret holding incidentrelay.conf.
*/}}
{{- define "incidentrelay.configSecretName" -}}
{{- default (printf "%s-config" (include "incidentrelay.fullname" .)) .Values.existingConfigSecret }}
{{- end }}

{{/*
Validate chart-rendered configuration before creating workloads. Use get/default
so upgrades that reuse pre-2.0 values fail cleanly instead of dereferencing a
missing nested map.
*/}}
{{- define "incidentrelay.validateValues" -}}
{{- if not .Values.existingConfigSecret -}}
{{- $config := default (dict) .Values.config -}}
{{- $main := default (dict) (get $config "main") -}}
{{- $mainSecret := required "config.main.secret_key is required; set a unique random value or use existingConfigSecret" (get $main "secret_key") -}}
{{- $knownInsecure := list "dev-secret-key" "change-me" "change-this-secret-key" "change-this-jwt-secret" "change-this-mattermost-action-secret" -}}
{{- if has ($mainSecret | toString | trim) $knownInsecure -}}
{{- fail "config.main.secret_key uses a known insecure default; set a unique cryptographically random value" -}}
{{- end -}}
{{- $secretEncryptionKey := default $mainSecret (get $main "secret_encryption_key") -}}
{{- if has ($secretEncryptionKey | toString | trim) $knownInsecure -}}
{{- fail "config.main.secret_encryption_key uses a known insecure default; set a unique cryptographically random value or leave it empty to inherit main.secret_key" -}}
{{- end -}}
{{- $auth := default (dict) (get $config "auth") -}}
{{- $jwtSecret := default $mainSecret (get $auth "jwt_secret") -}}
{{- if has ($jwtSecret | toString | trim) $knownInsecure -}}
{{- fail "config.auth.jwt_secret uses a known insecure default; set a unique cryptographically random value or leave it empty to inherit main.secret_key" -}}
{{- end -}}
{{- $mattermost := default (dict) (get $config "mattermost") -}}
{{- $mattermostSecret := default $mainSecret (get $mattermost "action_secret") -}}
{{- if has ($mattermostSecret | toString | trim) $knownInsecure -}}
{{- fail "config.mattermost.action_secret uses a known insecure default; set a unique cryptographically random value or leave it empty to inherit main.secret_key" -}}
{{- end -}}
{{- $voice := default (dict) (get $config "voice") -}}
{{- $voiceSecret := default $mainSecret (get $voice "callback_secret") -}}
{{- if has ($voiceSecret | toString | trim) $knownInsecure -}}
{{- fail "config.voice.callback_secret uses a known insecure default; set a unique cryptographically random value or leave it empty to inherit main.secret_key" -}}
{{- end -}}
{{- $database := default (dict) (get $config "database") -}}
{{- $dbType := default "sqlite" (get $database "type") | toString -}}
{{- if and (eq $dbType "sqlite") (not .Values.persistence.enabled) -}}
{{- fail "SQLite requires persistence.enabled=true so web and worker pods share the same database; use PostgreSQL before disabling persistence" -}}
{{- end -}}
{{- if and (eq $dbType "sqlite") (gt (int .Values.web.replicaCount) 1) -}}
{{- fail "SQLite supports only web.replicaCount=1 in this chart; use PostgreSQL before scaling the web deployment" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Return a normalized 2.0 config map. This makes old Helm values safe to reuse:
security-related options introduced after 1.x are materialized before the INI
file is rendered, so the container entrypoint never generates different keys
inside separate PostgreSQL/multi-node pods.
*/}}
{{- define "incidentrelay.config" -}}
{{- if not .Values.existingConfigSecret -}}
{{- include "incidentrelay.validateValues" . -}}
{{- end -}}
{{- $config := deepCopy (default (dict) .Values.config) -}}
{{- $main := default (dict) (get $config "main") -}}
{{- $mainSecret := default "" (get $main "secret_key") -}}
{{- $_ := set $main "secret_encryption_key" (default $mainSecret (get $main "secret_encryption_key")) -}}
{{- $_ = set $config "main" $main -}}

{{- $authDefaults := dict
      "api_auth_required" true
      "rbac_enforced" true
      "jwt_secret" ""
      "jwt_expire_minutes" 1440
      "jwt_cookie_name" "incidentrelay_jwt"
      "jwt_cookie_secure" false
      "login_ip_max_failures" 60
      "login_ip_window_seconds" 60
      "login_ip_block_seconds" 60
      "login_account_max_failures" 20
      "login_account_window_seconds" 300
      "login_account_block_seconds" 300 -}}
{{- $auth := mergeOverwrite $authDefaults (default (dict) (get $config "auth")) -}}
{{- $_ = set $auth "jwt_secret" (default $mainSecret (get $auth "jwt_secret")) -}}
{{- $_ = set $config "auth" $auth -}}

{{- $mattermost := default (dict) (get $config "mattermost") -}}
{{- $_ = set $mattermost "action_secret" (default $mainSecret (get $mattermost "action_secret")) -}}
{{- $_ = set $config "mattermost" $mattermost -}}

{{- $voice := default (dict) (get $config "voice") -}}
{{- $_ = set $voice "callback_secret" (default $mainSecret (get $voice "callback_secret")) -}}
{{- $_ = set $config "voice" $voice -}}

{{ range $section, $options := $config -}}
[{{ $section }}]
{{ range $key, $value := $options -}}
{{ $key }} = {{ $value }}
{{ end }}
{{ end -}}
{{- end }}


{{/*
Keep worker pods on the web pod's node whenever the shared data volume is
enabled. This makes the default ReadWriteOnce PVC schedulable for every worker
and also keeps the SQLite deployment on one node.
*/}}
{{- define "incidentrelay.dataWorkerAffinity" -}}
podAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          {{- include "incidentrelay.selectorLabels" . | nindent 10 }}
          app.kubernetes.io/component: web
      topologyKey: kubernetes.io/hostname
{{- end }}

{{/*
Name of the PVC backing /var/lib/incidentrelay.
*/}}
{{- define "incidentrelay.dataClaimName" -}}
{{- default (printf "%s-data" (include "incidentrelay.fullname" .)) .Values.persistence.existingClaim }}
{{- end }}

{{/*
Volumes shared by every component.
*/}}
{{- define "incidentrelay.volumes" -}}
- name: config
  secret:
    secretName: {{ include "incidentrelay.configSecretName" . }}
- name: data
  {{- if .Values.persistence.enabled }}
  persistentVolumeClaim:
    claimName: {{ include "incidentrelay.dataClaimName" . }}
  {{- else }}
  emptyDir: {}
  {{- end }}
- name: logs
  emptyDir: {}
{{- with .Values.extraVolumes }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Volume mounts shared by every component.
*/}}
{{- define "incidentrelay.volumeMounts" -}}
- name: config
  mountPath: /etc/incidentrelay
  readOnly: true
- name: data
  mountPath: /var/lib/incidentrelay
- name: logs
  mountPath: /var/log/incidentrelay
{{- with .Values.extraVolumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Pod annotation with the config checksum so config changes roll pods.
Empty when an existing Secret is used (the chart cannot see its content).
*/}}
{{- define "incidentrelay.configChecksum" -}}
{{- if not .Values.existingConfigSecret -}}
checksum/config: {{ include "incidentrelay.config" . | sha256sum }}
{{- end }}
{{- end }}
