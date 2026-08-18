# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http:#www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# wolfi-base is intentionally tracked at :latest to match the established EDI
# Wolfi pattern (os-wellbore-ddms-aws). Trade-off: :latest is mutable, so image
# builds are not byte-reproducible over time.
FROM public.ecr.aws/chainguard/wolfi-base:latest as build

LABEL version="1.0"
LABEL maintainer="aws"

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.python/bin:${PATH}"

ARG version=3.13
RUN apk add python-${version} py${version}-pip --no-cache

RUN python3 -m venv "/app/.python/"

ARG PIP_INDEX_URL
ENV PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple https://community.opengroup.org/api/v4/projects/148/packages/pypi/simple"

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY ./src/wdmsworker ./src/wdmsworker

RUN /app/.python/bin/pip install pip==26.1.2 setuptools==78.1.1
RUN /app/.python/bin/pip install --no-cache-dir --only-binary=:all: -v .[aws]

FROM public.ecr.aws/chainguard/wolfi-base:latest as service

LABEL version="1.0"
LABEL maintainer="aws"

ARG version=3.13
RUN apk add python-${version} bash openssl --no-cache

COPY --from=build /app /app

ARG PIP_INDEX_URL

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY ./src/wdmsworker ./src/wdmsworker

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp/app
ENV PATH="/app/.python/bin:${PATH}"

COPY provider/os-wellbore-ddms-worker-aws/build-aws/entrypoint.sh .
COPY provider/os-wellbore-ddms-worker-aws/build-aws/osdu_api.ini .
COPY provider/os-wellbore-ddms-worker-aws/build-aws/ssl.sh .
ENV PYTHONPATH=./src

#Default to using self signed generated TLS cert
ENV USE_SELF_SIGNED_SSL_CERT "true"
ENV SSL_CERT_PATH "./aws/certs/cert.crt"
ENV SSL_KEY_PATH "./aws/certs/cert.key"
ENV SSL_ENABLED "true"

EXPOSE ${APPLICATION_PORT}

RUN addgroup -S -g 10001 appgroup \
 && adduser -S -H -u 10001 -G appgroup appuser

USER 10001:10001
ENTRYPOINT ["/bin/sh", "-c", "/entrypoint.sh"]
