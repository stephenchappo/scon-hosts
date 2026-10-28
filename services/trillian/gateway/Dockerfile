# Test stage: deploy.sh runs the suite against the candidate tables before switching.
FROM python:3.12-slim AS test
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest==9.2.0
COPY app/ app/
COPY tests/ tests/
ENV GATEWAY_TABLES=/tables
CMD ["python3", "-m", "pytest", "-q", "tests"]

FROM python:3.12-slim AS service
RUN useradd --uid 10001 --create-home gw
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
USER gw
EXPOSE 8640
CMD ["uvicorn", "app.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8640", "--no-server-header"]
