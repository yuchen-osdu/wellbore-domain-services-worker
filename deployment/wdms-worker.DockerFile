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

FROM python:3.11-slim-bookworm

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY ./src/wdmsworker ./src/wdmsworker

ENV PIP_EXTRA_INDEX_URL=https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple
RUN pip install -v .[az]  #  currently Azure specific
RUN rm -rf ./src/wdmsworker  # must use multi layer instead ?

EXPOSE 8080
WORKDIR ./

# Make the container run as non-root user
RUN addgroup --system appuser && adduser --system appuser && adduser appuser appuser


################## FIX CVEs contained in Debian bookworm ##################
RUN apt-get update && \
    # Fix CVE-2024-28085 (https://security-tracker.debian.org/tracker/source-package/util-linux)
    apt-get --only-upgrade install util-linux-extra=2.38.1-5+deb12u1 -y && \
    # Fix CVE-2024-2961 (https://security-tracker.debian.org/tracker/source-package/glibc)
    apt-get --only-upgrade install libc6=2.36-9+deb12u7 -y
###### Some pacakges are fixed only with trixie (Debian 13) release. ######
RUN touch /etc/apt/sources.list.d/trixie.list && \
    printf "deb https://deb.debian.org/debian trixie main" > /etc/apt/sources.list.d/trixie.list
RUN apt-get update &&  \
    # Fix CVE-2023-45853 (https://security-tracker.debian.org/tracker/source-package/zlib)
    apt-get --only-upgrade install zlib1g=1:1.3.dfsg+really1.3.1-1 && \
    # Fix CVE-2023-7104 (https://security-tracker.debian.org/tracker/source-package/sqlite3)
    apt-get --only-upgrade install libsqlite3-0=3.46.0-1 -y  && \
    # Fix CVE-2023-31484 (https://security-tracker.debian.org/tracker/source-package/perl)
    apt-get --only-upgrade install perl-base=5.38.2-5 -y && \
    # Fix CVE-2023-52425 (https://security-tracker.debian.org/tracker/source-package/expat)
    apt-get --only-upgrade install libexpat1=2.6.2-1 -y
# Prevent CVE-2024-26462 by delete unnecessary libraries
RUN apt-get purge libkrb5-3 libk5crypto3 libkrb5support0 -y
####################################################################################################


USER appuser

CMD ["uvicorn", "wdmsworker.app:base", "--host", "0.0.0.0", "--port", "8080"]
