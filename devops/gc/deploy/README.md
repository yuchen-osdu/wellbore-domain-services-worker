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

You need to set variables in **values.yaml** file using any code editor. Some of the values are prefilled, but you need to specify some values as well. You can find more information about them below.

### Global Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **global.domain** | your domain for an external endpoint, ex `example.com` | string | `-` | yes |
| **global.limitsEnabled** | whether CPU and memory limits are enabled | boolean | `true` | yes |
| **global.tier** | tier defines the number of replicas for the service to ensure the service HA; values are `DEV`, `STAGE`, `PROD` | string | "" | no |
| **global.autoscalingMode** | enables horizontal pod autoscaling on cluster spot nodes; values are `none`, `cpu`, `requests` | string | `cpu` | yes |
| **global.logLevel** | severity of logging level | string | `ERROR` | yes |

### Configmap Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **data.openapiPrefix** | OpenAPI prefix | string | `/api/wdms-worker` | yes |

### Deployment Variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **data.requestsCpu** | amount of requested CPU | string | `40m` | yes |
| **data.requestsMemory** | amount of requested memory| string | `350Mi` | yes |
| **data.limitsCpu** | CPU limit | string | `1` | only if `global.limitsEnabled` is true |
| **data.limitsMemory** | memory limit | string | `1G` | only if `global.limitsEnabled` is true |
| **data.gcImage** | Service image for GC env | string | `community.opengroup.org:5555/osdu/platform/domain-data-mgmt-services/wellbore/wellbore-domain-services-worker/gc-wellbore-worker-master:latest` | yes |
| **data.imagePullPolicy** | when to pull image | string | `IfNotPresent` | yes |
| **data.serviceAccountName** | k8s service account name for the application | string | `wellbore-worker` | yes |
| **data.logLevel** | logging severity level for this service only | string | - | yes, only if differs from the `global.logLevel` |

### Config Variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **conf.appName** | Service name | string | `wellbore-worker` | yes |
| **conf.configmap** | configmap to be used | string | `wellbore-worker-config` | yes |

### Horizontal Pod Autoscaling (HPA) variables

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

| Name                     | Description                                     | Type    | Default | Required                                       |
|--------------------------|-------------------------------------------------|---------|---------|------------------------------------------------|
| **limits.maxTokens**     | maximum number of requests per fillInterval     | integer | `12`    | only if `global.autoscalingMode` is `requests` |
| **limits.tokensPerFill** | number of new tokens allowed every fillInterval | integer | `12`    | only if `global.autoscalingMode` is `requests` |
| **limits.fillInterval**  | time interval                                   | string  | `"1s"`  | only if `global.autoscalingMode` is `requests` |

### Autoscaling

By default, autoscaling is configured for deployments targeting spot nodes. Pods will attempt to schedule on nodes with specific labels indicating they are spot instances. To adjust how pods are scheduled, you can update the `data.affinityLabelsSpot` in your values.yaml file.

Example:

```yml
data:
  affinityLabelsSpot:
    mylabel:
      - value1
      - test
    newLabel:
      - newValue
```

Each label, along with its values, will be translated into a separate `- matchExpressions` block within the `nodeAffinity` section of your deployment. This configuration operates with OR logic, meaning pods will be scheduled on any node that possesses at least one of the specified labels with one of its defined values.

The chart uses the `global.autoscalingMode` parameter in your `values.yaml` to control how autoscaling behaves. This parameter accepts three possible string values:

* **cpu** (default): Autoscaling is enabled and is based on CPU utilization. This is the default setting.
* **requests**: Autoscaling is enabled and is based on resource requests (custom metrics). **NOTE**: Prometheus should be installed in your cluster, custom metrics are used for this type of autoscaling.
* **none**: Autoscaling is entirely disabled for the application. Setting `global.autoscalingMode` to **none** also prevents the creation of the spot deployment.

The `global.tier` parameter controls the number of replicas based on the environment:

* **DEV**: 1-5 replicas
* **STAGE**: 2-7 replicas  
* **PROD**: 3-10 replicas
* **"" (empty)**: Uses `hpa.minReplicas` and `hpa.maxReplicas` values

### Methodology for Parameter Calculation variables: **hpa.requests.targetValue**, **limits.maxTokens** and **limits.tokensPerFill**

The parameters **hpa.requests.targetValue**, **limits.maxTokens** and **limits.tokensPerFill** were determined through empirical testing during load testing. These tests were conducted using the N2D machine series, which can run on either AMD EPYC Milan or AMD EPYC Rome processors. The values were fine-tuned to ensure optimal performance under typical workloads.

### Recommendations for New Instance Types

When changing the instance type to a newer generation, such as the C3D series, it is essential to conduct new load testing. This ensures the parameters are recalibrated to match the performance characteristics of the new processor architecture, optimizing resource utilization and maintaining application stability.

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
