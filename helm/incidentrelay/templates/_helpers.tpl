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
Render the values under .Values.config as an INI file.
*/}}
{{- define "incidentrelay.config" -}}
{{- range $section, $options := .Values.config }}
[{{ $section }}]
{{- range $key, $value := $options }}
{{ $key }} = {{ $value }}
{{- end }}
{{ end }}
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
