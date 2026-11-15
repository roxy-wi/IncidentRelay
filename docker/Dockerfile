# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

FROM base AS builder

WORKDIR /build

# Compile extensions here; build tools never enter the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /build/requirements.txt

# The PostgreSQL wheel bundles libpq on both supported Linux architectures.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir \
       --only-binary=psycopg2-binary -r requirements.txt

FROM base AS runtime

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /opt/incidentrelay

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        passwd \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 incidentrelay \
    && useradd --uid 10001 --gid 10001 --create-home \
         --home-dir /home/incidentrelay --shell /bin/bash incidentrelay

COPY --from=builder /opt/venv /opt/venv
COPY . /opt/incidentrelay

RUN mkdir -p \
      /etc/incidentrelay \
      /var/lib/incidentrelay \
      /var/log/incidentrelay \
      /usr/local/lib/incidentrelay/voice_providers \
    && chown incidentrelay:incidentrelay \
       /var/lib/incidentrelay /var/log/incidentrelay

COPY docker/incidentrelay.docker.conf /etc/incidentrelay/incidentrelay.conf
COPY --chmod=0755 docker/entrypoint.sh /entrypoint.sh

ENV HOME=/home/incidentrelay
ENV INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
ENV INCIDENTRELAY_SERVICE=web

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
