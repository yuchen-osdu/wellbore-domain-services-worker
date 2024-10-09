
FROM python:3.10-slim-bullseye

WORKDIR /

COPY ../../pyproject.toml .
COPY ../../README.md .
COPY ../../src/wdmsworker src/wdmsworker

ENV PIP_EXTRA_INDEX_URL="https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple https://community.opengroup.org/api/v4/projects/224/packages/pypi/simple"
RUN pip install -v ."[ibm]"
# RUN rm -rf ./src/wdmsworker

EXPOSE 8080


ENV CLOUD_PROVIDER=ibm

# Make the container run as non-root user
RUN addgroup --system appuser && adduser --system appuser && adduser appuser appuser

USER appuser

CMD ["uvicorn", "wdmsworker.app:base", "--host", "0.0.0.0", "--port", "8080"]
