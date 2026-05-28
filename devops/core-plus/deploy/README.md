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
| **global.limitsEnabled** | whether CPU and memory limits are enabled | boolean | `true` | yes |

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
| **data.image** | Service image for GC env | string | `-` | yes |
| **data.imagePullPolicy** | when to pull image | string | `IfNotPresent` | yes |
| **data.serviceAccountName** | k8s service account name for the application | string | `wellbore-worker` | yes |

### Config Variables

| Name | Description | Type | Default |Required |
|------|-------------|------|---------|---------|
| **conf.appName** | Service name | string | `wellbore-worker` | yes |
| **conf.configmap** | configmap to be used | string | `wellbore-worker-config` | yes |
|**conf.s3SecretName** | secret for S3/SeaweedFS storage(prefixed with `global.dataPartitionId`) | string | `wellbore-seaweedfs-secret` | yes |
| **conf.replicas** | Number of replicas for the application k8s deployment | digit | `1` | yes |

### Installing the Helm Chart

To install the Helm Chart, run the following command from within this directory:

```console
helm install core-plus-wellbore-worker-deploy .
```

## Uninstalling the Helm Chart

To uninstall the Helm deployment, execute the following command:

```console
helm uninstall core-plus-wellbore-worker-deploy
```

> Remember to delete all the Service specific Kubernetes secrets and/or PVCs after uninstalling the Service.
