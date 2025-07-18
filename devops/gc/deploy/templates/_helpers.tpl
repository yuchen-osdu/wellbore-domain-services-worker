#  Copyright 2025 Google LLC
#  Copyright 2025 EPAM
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

# Function to check the value of the global.tier
{{- define "wellboreWorker.getTier" -}}
{{- $tier := .Values.global.tier -}}
{{- $allowedTiers := list "" "DEV" "STAGE" "PROD" -}}

{{- if not (has $tier $allowedTiers) -}}
  {{- fail (printf "Invalid 'global.tier' value: '%s'. Must be one of %v." $tier $allowedTiers) -}}
{{- end -}}
{{- $tier -}}
{{- end -}}

# Function to check the value of the global.autoscalingMode
{{- define "wellboreWorker.getAutoscaling" -}}
{{- $scale := .Values.global.autoscalingMode -}}
{{- $allowedScale := list "none" "cpu" "requests" -}}

{{- if not (has $scale $allowedScale) -}}
  {{- fail (printf "Invalid 'global.autoscalingMode' value: '%s'. Must be one of %v." $scale $allowedScale) -}}
{{- end -}}
{{- end -}}

# Function to define the minimum number of replicas for spot deployment
{{- define "wellboreWorker.minReplicasSpot" -}}
{{- $tier := include "wellboreWorker.getTier" . -}}

{{- if eq $tier "DEV" -}} 1
{{- else if eq $tier "STAGE" -}} 2
{{- else if eq $tier "PROD" -}} 3
{{- else -}} {{ .Values.hpa.minReplicas }}
{{- end -}}
{{- end -}}

# Function to define the maximum number of replicas for spot deployment
{{- define "wellboreWorker.maxReplicasSpot" -}}
{{- $tier := include "wellboreWorker.getTier" . -}}

{{- if eq $tier "DEV" -}} 5
{{- else if eq $tier "STAGE" -}} 7
{{- else if eq $tier "PROD" -}} 10
{{- else -}} {{ sub .Values.hpa.maxReplicas 1 }}
{{- end -}}
{{- end -}}
