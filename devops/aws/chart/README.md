# OSDU on AWS Service Helm Chart

## Introduction
The following document outlines how to deploy and update the service application onto an existing Kubernetes deployment using the [Helm](https://helm.sh) package manager.

## Prerequisites
The below software must be installed before continuing:
* [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
* [kubectl](https://kubernetes.io/docs/tasks/tools/)
* [Helm](https://helm.sh/docs/intro/install/)
* [Helm S3 Plugin](https://github.com/hypnoglow/helm-s3)

Additionally, an OSDU on AWS environment must be deployed.

## Installation/Updating
To install or update the service application by executing the following command in the CHART folder:

```bash
helm upgrade [RELEASE_NAME] . -i -n [NAMESPACE]
```

To observe the Kubernetes resources before deploying them using the command:
```bash
helm upgrade [RELEASE_NAME] . -i -n [NAMESPACE] --dry-run --debug
```

To observe the history of the current release, use the following command:
```bash
helm history [RELEASE_NAME] -n [NAMESPACE]
```

To revert to a previous release, use the following command:
```bash
helm rollback [RELEASE] [REVISION] -n [NAMESPACE]
```

Refer to the [Helm CLI guide](https://helm.sh/docs/helm/helm/) for additional commands.

## Customizing the Deployment
It is possible to modify the default values specified in the **values.yaml** file using the --set option. The below parameters can be modified by advanced users to customize the deployment configuration:

### Globals
Global Helm values apply to all services within the parent chart deployment. Global values will not override service defaults or locally set values.
| Name | Example Value | Description | Type | Required |
| ---  | ------------- | ----------- | ---- | -------- |
| `global.allowOrigins` | `{http://localhost,https://www.osdu.aws}` | A list of domains that are permitted by CORS policy. An empty list permits all origins. | array[str] | no |
| `global.metricsServerAddress` | `http://prometheus-service.monitoring:8080` | The URL of the accessible metrics server for evaluating autoscaling decisions. | str | no |
| `global.podAnnotations` | `podAnnotations.version=v1.0.0` | Additional annotations on the service pod | dict | no |
| `global.podSecurityContext` | `fsGroup: 1337` | The [pod security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) apply to all containers in the pod | str | no |
| `global.securityContext` | `fsGroup: 1337` | The security context is the container specific security context. Will inherit [pod security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) | str | no |

### Local
Local Helm values apply to specific services. Local Helm values will override global values and default presets.
| Name | Example Value | Description | Type | Required |
| ---  | ------------- | ----------- | ---- | -------- |
| `image` | `registry.repo.osdu.aws/service:0.21.0` | The custom image of the service deployment. | str | no |
| `imagePullPolicy` | `IfNotPresent` | The service image pull policy | str | no |
| `resources.limits.cpu` | `500M` | [CPU resource management limit for pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) | str | no |
| `resources.limits.memory` | `900M` | [Memory resource management limit for pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) | str | no |
| `resources.requests.cpu` | `500M` | [MemoCPUry resource management for pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) | str | no |
| `resources.requests.memory` | `900M` | [Memory resource management for pods](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) | str | no |
| `replicaCount` | `1` | The number of pod replicas to be initially deployed | int | no |
| `autoscaling.minReplicas` | `1` | Minimum number of pod replicas | int | no |
| `autoscaling.maxReplicas` | `100` | Maximum number of pod replicas | int | no |
| `autoscaling.targetCPUUtilizationPercentage` | `80` | CPU utilization target | int | no |
| `autoscaling.targetMemoryUtilizationPercentage` | `80` | Memory utilization target | int | no |
| `autoscaling.ServiceRequestCountThreshold` | `25` | The number of requests per second threshold averaged over a minute to trigger a scaling event. | int | no |
| `autoscaling.ServiceRequestDurationAverage` | `300` | The response time measured in miliseconds averaged over 3 minutes to trigger a scaling event. | int | no |
| `autoscaling.coolDownPeriod` | `120` | The period to wait after the last trigger reported active before scaling the resource back to 0. Managed by Keda. | int | no |
| `autoscaling.pollingInterval` | `1` | This is the interval to check each trigger on. | int | no |
| `livenessProbe.failureThreshold` | `3` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `livenessProbe.periodSeconds` | `10` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `livenessProbe.successThreshold` | `1` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `livenessProbe.timeoutSeconds` | `1` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `readinessProbe.initialDelaySeconds` | `30` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `readinessProbe.failureThreshold` | `3` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `readinessProbe.periodSeconds` | `10` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `readinessProbe.successThreshold` | `1` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `readinessProbe.timeoutSeconds` | `1` | [Kubernetes probe configuration](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/#configure-probes). | int | no |
| `maxPendingRequests` | `10000` | Maximum number of requests that will be queued while waiting for a ready connection pool connection. Used for circuit breaking. Used for [circuit breaking.](https://istio.io/latest/docs/tasks/traffic-management/circuit-breaking/). | int | no |
| `maxRequestsPerConnection` | `100` | Maximum number of active requests to a destination. Used for [circuit breaking.](https://istio.io/latest/docs/tasks/traffic-management/circuit-breaking/). | int | no |
| `maxConnections` | `0` | Maximum number of HTTP1 /TCP connections to a destination host. Used for [circuit breaking.](https://istio.io/latest/docs/tasks/traffic-management/circuit-breaking/). | int | no |
| `podAnnotations` | `podAnnotations.version=v1.0.0` | Additional annotations on the service pod | dict | no |
| `podSecurityContext` | `fsGroup: 1337` | The [pod security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) apply to all containers in the pod | str | no |
| `securityContext` | `fsGroup: 1337` | The security context is the container specific security context. Will inherit [pod security context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) | str | no |

## Uninstalling the Chart
To uninstall the helm release:

```bash
helm uninstall [RELEASE] -n [NAMESPACE] --keep-history
```