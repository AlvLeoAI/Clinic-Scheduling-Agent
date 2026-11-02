# API image. Runtime dependencies only; configuration comes from environment variables
# (no .env is copied). Migrations and seeding are one-off commands, never run on start:
#   docker run --rm --env-file … IMAGE sh -c "alembic upgrade head && python -m scripts.seed"
ARG PYTHON_IMAGE=python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-deps -r /tmp/requirements-runtime.lock
# AWS RDS CA bundle for sslmode=verify-full, pinned by SHA-256: if AWS rotates the file
# the build fails here instead of shipping an unverified trust anchor.
ARG RDS_CA_URL=https://truststore.pki.rds.amazonaws.com/us-east-2/us-east-2-bundle.pem
ARG RDS_CA_SHA256=d46e1bdfda05c8e7644e50930806a19b139a222542bf0348082fb59ece2b5fa5
RUN python -c "import hashlib, sys, urllib.request; \
data = urllib.request.urlopen(sys.argv[1], timeout=30).read(); \
assert hashlib.sha256(data).hexdigest() == sys.argv[2], 'RDS CA bundle checksum mismatch'; \
open('/tmp/rds-ca-bundle.pem', 'wb').write(data)" "$RDS_CA_URL" "$RDS_CA_SHA256"

FROM ${PYTHON_IMAGE}
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin clinic
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY --from=build /tmp/rds-ca-bundle.pem /etc/ssl/certs/rds-ca-bundle.pem
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts/__init__.py scripts/seed.py scripts/purge_chat.py scripts/db_roles.py ./scripts/
USER 10001
EXPOSE 8000
# Liveness only: readiness (/api/v1/health) also checks the database.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
