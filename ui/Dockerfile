# UI image (build context: ui/). It talks only to the API at API_BASE_URL and has no
# database driver. Streamlit keeps session state in process memory. The 30 s websocket
# ping keeps idle sessions open through CloudFront and the load balancer (idle 300 s).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock /tmp/requirements.lock
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-deps --require-hashes -r /tmp/requirements.lock

FROM ${PYTHON_IMAGE}
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none STREAMLIT_CLIENT_TOOLBAR_MODE=minimal \
    STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=false STREAMLIT_SERVER_WEBSOCKET_PING_INTERVAL=30
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin clinic
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY __init__.py client.py confirmation.py app.py ./ui/
USER 10001
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"]
CMD ["streamlit", "run", "ui/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
