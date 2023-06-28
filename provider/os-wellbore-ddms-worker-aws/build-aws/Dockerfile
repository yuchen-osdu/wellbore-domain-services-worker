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

FROM python:3.10-slim-bullseye
ARG PIP_INDEX_URL

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY ./src/wdmsworker ./src/wdmsworker

ENV PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple https://community.opengroup.org/api/v4/projects/148/packages/pypi/simple"
RUN pip install -v .[aws]

COPY provider/os-wellbore-ddms-worker-aws/build-aws/entrypoint.sh .
COPY provider/os-wellbore-ddms-worker-aws/build-aws/osdu_api.ini .
COPY provider/os-wellbore-ddms-worker-aws/build-aws/ssl.sh .
ENV PYTHONPATH=./

#Default to using self signed generated TLS cert
ENV USE_SELF_SIGNED_SSL_CERT "true"
ENV SSL_CERT_PATH "./aws/certs/cert.crt" 
ENV SSL_KEY_PATH "./aws/certs/cert.key"
ENV SSL_ENABLED "true"


EXPOSE ${APPLICATION_PORT}
WORKDIR ./

ENTRYPOINT ["/bin/sh", "-c", "/entrypoint.sh"]
