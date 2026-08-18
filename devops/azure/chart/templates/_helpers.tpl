{{/*
Common Annotations
*/}}
{{- define "os-wellbore-ddms-worker.commonAnnotations" -}}
build-number: {{ .Values.annotations.buildNumber | quote }}
build-origin: {{ .Values.annotations.buildOrigin | quote }}
commit-branch: {{ .Values.annotations.commitBranch | quote }}
commit-id: {{ .Values.annotations.commitId | quote }}
{{- end}}
{{/*
Common Labels
*/}}
{{- define "os-wellbore-ddms-worker.commonLabels" -}}
app: os-wellbore-ddms-worker{{ include "os-wellbore-ddms-worker.name-suffix" . }}
env: {{ .Values.labels.env }}
{{ include "os-wellbore-ddms-worker.deploymentTypeLabels" . }}
{{- end }}

{{/*
 Creates a dynamic set of labels based on if the deployment is a temp Deployment or not.
*/}}
{{- define "os-wellbore-ddms-worker.deploymentTypeLabels" -}}
{{- if .Values.tempDeployment.enabled -}}
temporary-deployment: "{{ .Values.tempDeployment.name }}"
deployment-type: temporary
{{- else }}
deployment-type: standard
{{- end }}
{{- end }}

{{/*
 Renders the namespace. 
*/}}
{{- define "os-wellbore-ddms-worker.namespace" -}}
namespace: {{.Values.namespace}}
{{- end }}

{{/*
 Renders the pathPrefix and suffix if there is any 
*/}}
{{- define "os-wellbore-ddms-worker.prefix" -}}
{{ .Values.ingress.hosts.pathPrefix }}{{ include "os-wellbore-ddms-worker.name-suffix" . }}
{{- end }}

{{/*
 Creates a string suffix if the deployment is marked as temporary. 
*/}}
{{- define "os-wellbore-ddms-worker.name-suffix" -}}
{{- if .Values.tempDeployment.enabled -}}
{{- printf "---%s" .Values.tempDeployment.name -}}
{{- end -}}
{{- end -}}