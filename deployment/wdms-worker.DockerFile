FROM cgr.dev/chainguard/wolfi-base AS builder

ENV LANG=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/wdms-worker/venv/bin:$PATH"

WORKDIR /wdms-worker

ARG version=3.11
RUN apk add python-${version} py${version}-pip
RUN python3 -m venv /wdms-worker/venv

COPY pyproject.toml .
COPY ./src/wdmsworker ./wdmsworker

ENV PIP_EXTRA_INDEX_URL=https://community.opengroup.org/api/v4/projects/465/packages/pypi/simple
RUN pip3 install -v .[az] --no-cache-dir #  currently Azure specific


FROM cgr.dev/chainguard/wolfi-base AS production

EXPOSE 8080
WORKDIR /wdms-worker

ENV PYTHONUNBUFFERED=1
ENV PATH="/wdms-worker/venv/bin:$PATH"

ARG version=3.11
RUN apk add python-${version}

COPY --from=builder /wdms-worker/venv ./venv

USER nonroot

ENTRYPOINT ["uvicorn"]
CMD ["wdmsworker.app:base", "--host", "0.0.0.0", "--port", "8080"]
