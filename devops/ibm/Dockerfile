
# FROM python:3.10-slim-bullseye
FROM registry.access.redhat.com/ubi9/python-313

WORKDIR /

COPY ../../pyproject.toml .
COPY ../../README.md .
COPY ../../LICENSE .
COPY ../../src/wdmsworker src/wdmsworker

USER root
RUN chmod -R 755 ./src/

ENV PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple https://community.opengroup.org/api/v4/projects/224/packages/pypi/simple"
RUN pip install -v ."[ibm]"
# RUN rm -rf ./src/wdmsworker

EXPOSE 8080

ENV CLOUD_PROVIDER=ibm

# Make the container run as non-root user
USER 1001
CMD ["uvicorn", "wdmsworker.app:app", "--host", "0.0.0.0", "--port", "8080"]
