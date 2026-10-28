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
# Both listeners bind loopback; compose runs this with the host network so loopback is Trillian's.
CMD ["python3", "-m", "app.serve"]
