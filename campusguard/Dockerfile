FROM python:3.12-slim-bookworm AS build
ARG INSTALL_BIOMETRICS=true
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-server.txt requirements.lock ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && if [ "$INSTALL_BIOMETRICS" = "true" ]; then pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-server.txt -c requirements.lock; fi

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 campusguard && useradd --uid 10001 --gid 10001 --create-home campusguard
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/campusguard
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY app ./app
COPY static ./static
COPY scripts ./scripts
COPY migrations ./migrations
COPY campus_attendance.sql ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python","-c","import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4)"]
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000","--workers","1","--no-access-log","--no-proxy-headers","--limit-concurrency","64","--timeout-keep-alive","5"]
