# Copyright 2023 Schlumberger
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM python:3.10-slim-bullseye

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY ./src/wdmsworker ./src/wdmsworker

ENV PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/148/packages/pypi/simple https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple"
RUN pip install -v .[baremetal]
RUN rm -rf ./src/wdmsworker

EXPOSE 8080
WORKDIR ./

# Make the container run as non-root user
RUN addgroup --system appuser && adduser --system appuser && adduser appuser appuser

USER appuser

CMD ["uvicorn", "wdmsworker.app:base", "--host", "0.0.0.0", "--port", "8080"]
