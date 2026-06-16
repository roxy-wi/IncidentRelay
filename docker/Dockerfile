FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /opt/incidentrelay

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/incidentrelay/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn psycopg2-binary

COPY . /opt/incidentrelay

RUN mkdir -p \
      /etc/incidentrelay \
      /var/lib/incidentrelay \
      /var/log/incidentrelay \
      /usr/local/lib/incidentrelay/voice_providers

COPY docker/incidentrelay.docker.conf /etc/incidentrelay/incidentrelay.conf
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENV INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
ENV INCIDENTRELAY_SERVICE=web

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
