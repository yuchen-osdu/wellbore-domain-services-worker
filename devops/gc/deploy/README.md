# Deploy the Service Helm Chart

This guide provides instructions on deploying a Helm Chart on a [Kubernetes](https://kubernetes.io) cluster using the [Helm](https://helm.sh) package manager.

## Prerequisites

Tests for the code were performed on a **Kubernetes cluster** (v1.26.6) with **Istio** (1.13.3).
> It is possible to use other versions, but it hasn't been tested.

### Compatible Operating Systems

The code works on Debian-based Linux distributions (Debian 10 and Ubuntu 20.04) and Windows WSL2. Also, it may work (but it is not guaranteed) on Google Cloud Shell.

Other operating systems, including macOS, have not been verified and are currently unsupported.

### Required Packages

These packages are requisite for installation from a local computer:

- **Helm** (v3.9.3 or higher) [helm](https://helm.sh/docs/intro/install/)

- **Kubectl** (v1.26.0 or higher) [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)

## Installation

Use any code editor to set variables in the **values.yaml** file. Some of the values are prefilled. However, you'll need to specify some values as well.

Detailed information about these variables is provided below.

### Global Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **global.domain** | your domain for an external endpoint, ex `example.com` | string | `-` | yes |
| **global.onPremEnabled** | whether on-prem is enabled | boolean | `false` | yes |
| **global.limitsEnabled** | whether CPU and memory limits are enabled | boolean | `true` | yes |
| **global.tier** | Only PROD must be used to enable autoscaling | string | "" | no |
| **global.autoscaling** | enables horizontal pod autoscaling, when tier=PROD | boolean | true | yes |

### Configmap Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **data.openapiPrefix** | OpenAPI prefix | string | `/api/wdms-worker` | yes |

### Deployment Variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **data.requestsCpu** | amount of requested CPU | string | `5m` | yes |
| **data.requestsMemory** | amount of requested memory| string | `350Mi` | yes |
| **data.limitsCpu** | CPU limit | string | `1` | only if `global.limitsEnabled` is true |
| **data.limitsMemory** | memory limit | string | `1G` | only if `global.limitsEnabled` is true |
| **data.gcImage** | Service image for GC env | string | `community.opengroup.org:5555/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services-worker/gc-wellbore-worker-master:latest` | yes |
| **data.bmImage** | Service image for BM env | string | `community.opengroup.org:5555/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services-worker/bm-wellbore-worker-master:latest` | yes |
| **data.imagePullPolicy** | when to pull image | string | `IfNotPresent` | yes |
| **data.serviceAccountName** | k8s service account name for the application | string | `wellbore-worker` | yes |

### Config Variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **conf.appName** | Service name | string | `wellbore-worker` | yes |
| **conf.configmap** | configmap to be used | string | `wellbore-worker-config` | yes |
| **conf.minioSecretName** | MinIO secret name | string | `wellbore-minio-secret` | yes |
| **conf.replicas** | Number of replicas for the application k8s deployment | digit | `2` | yes |

### Horizontal Pod Autoscaling (HPA) variables (works only if tier=PROD and autoscaling=true)

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **hpa.minReplicas** | minimum number of replicas | integer | 6 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.maxReplicas** | maximum number of replicas | integer | 15 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.targetType** | type of measurements: AverageValue or Value | string | "AverageValue" | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.targetValue** | threshold value to trigger the scaling up | integer | 140 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleUpStabilizationWindowSeconds** | time to start implementing the scale up when it is triggered | integer | 10 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleUpPoliciesValue** | the maximum number of new replicas to create (in percents from current state)| integer | 50 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleUpPoliciesPeriodSeconds** | pause for every new scale up decision | integer | 15 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleDownStabilizationWindowSeconds** | time to start implementing the scale down when it is triggered | integer | 60 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleDownPoliciesValue** | the maximum number of replicas to destroy (in percents from current state) | integer | 25 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **hpa.behaviorScaleDownPoliciesPeriodSeconds** | pause for every new scale down decision | integer | 60 | only if `global.autoscaling` is true and `global.tier` is PROD |

### Limits variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **limits.maxTokens** | maximum number of requests per fillInterval | integer | 80 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **limits.tokensPerFill** | number of new tokens allowed every fillInterval | integer | 80 | only if `global.autoscaling` is true and `global.tier` is PROD |
| **limits.fillInterval** | time interval | string | "1s" | only if `global.autoscaling` is true and `global.tier` is PROD |

### Installing the Helm Chart

To install the Helm Chart, run the following command from within this directory:

```console
helm install gc-wellbore-worker-deploy .
```

## Uninstalling the Helm Chart

To uninstall the Helm deployment, execute the following command:

```console
helm uninstall gc-wellbore-worker-deploy
```

> Remember to delete all the Service specific Kubernetes secrets and/or PVCs after uninstalling the Service.
