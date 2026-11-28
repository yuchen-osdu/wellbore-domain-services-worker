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
| **global.domain** | your domain, ex `example.com`. Not used by this chart, but may be used in different deployment setups. Use `global.hostname` for the route host | string | - | no |
| **global.hostname** | host the `HTTPRoute` attaches to when `httpRoute.hostnames` is empty, ex `osdu.example.com` | string | `""` | only if `httpRoute.enabled` is true and `httpRoute.hostnames` is empty |
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

### Routing (HTTPRoute)

The chart owns the routing for the service. It renders a Gateway API `HTTPRoute`, disabled by default. The chart no longer ships an Istio `VirtualService`.

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **httpRoute.enabled** | render the `HTTPRoute` | boolean | `false` | yes |
| **httpRoute.name** | route name. When empty the name is `<release>-route`, which differs from any route of the same name defined outside this chart | string | `""` | no |
| **httpRoute.parentRefs** | gateways the route attaches to | list | `cimpl-gateway` in `istio-system` | yes |
| **httpRoute.hostnames** | hosts the route serves. When empty, `global.hostname` is used | list | `[]` | one of `httpRoute.hostnames` or `global.hostname` |
| **httpRoute.routes** | one rule per entry, see below | list | `/api/wdms-worker/` | yes |

The render fails when `httpRoute.enabled` is true and both `httpRoute.hostnames` and `global.hostname` are empty, so the route is never exposed on all hosts.

Each entry of `httpRoute.routes` accepts:

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| **path** | path to match | string | - | yes |
| **pathType** | match type, `PathPrefix` or `Exact` | string | `PathPrefix` | no |
| **serviceName** | backend Service name | string | `conf.appName` | no |
| **port** | backend Service port | integer | `80` | no |
| **filters** | Gateway API filters, for example `URLRewrite` | list | - | no |

Example, a route with a rewrite and another port:

```yaml
httpRoute:
  enabled: true
  hostnames:
    - osdu.example.com
  routes:
    - path: /api/wdms-worker/
    - path: /other/
      port: 9002
      filters:
        - type: URLRewrite
          urlRewrite:
            path:
              type: ReplacePrefixMatch
              replacePrefixMatch: /
```

### Installing the Helm Chart

To install the Helm Chart, run the following command from within this directory:

```console
helm install core-plus-wellbore-worker-deploy .
```

To expose the service through the Gateway API:

```console
helm install core-plus-wellbore-worker-deploy . --set httpRoute.enabled=true --set global.hostname=osdu.example.com
```

To check the rendered route without installing:

```console
helm template core-plus-wellbore-worker-deploy . --set httpRoute.enabled=true --set global.hostname=osdu.example.com -s templates/httproute.yaml
```

## Uninstalling the Helm Chart

To uninstall the Helm deployment, execute the following command:

```console
helm uninstall core-plus-wellbore-worker-deploy
```

> Remember to delete all the Service specific Kubernetes secrets and/or PVCs after uninstalling the Service.
