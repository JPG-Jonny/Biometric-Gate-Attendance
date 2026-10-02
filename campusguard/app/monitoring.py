"""Bounded labels and JSON logs. Never log payloads, credentials or query strings."""
import json
import logging
import time
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class JsonFormatter(logging.Formatter):
    def format(self, record):
        event = {'time': self.formatTime(record), 'level': record.levelname, 'message': record.getMessage()}
        for key in ('request_id', 'route', 'method', 'status', 'duration_seconds'):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event)


def configure_logging():
    logger = logging.getLogger('campusguard')
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter('campusguard_http_requests_total', 'HTTP requests', ['method', 'route', 'status'], registry=self.registry)
        self.latency = Histogram('campusguard_http_duration_seconds', 'HTTP duration', ['method', 'route'], registry=self.registry,
                                 buckets=(.01, .05, .1, .25, .5, 1, 2.5, 5, 10, 20))
        self.auth = Counter('campusguard_auth_total', 'Sign-in outcomes', ['outcome'], registry=self.registry)
        self.scans = Counter('campusguard_scans_total', 'Scan decisions, including retries', ['outcome'], registry=self.registry)
        self.db_errors = Counter('campusguard_database_errors_total', 'Database errors', registry=self.registry)
        self.ready = Gauge('campusguard_database_ready', 'Database probe succeeded', registry=self.registry)

    def render(self):
        return generate_latest(self.registry)


class MonitoringMiddleware:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id, start, status = uuid4().hex, time.perf_counter(), 500

        async def wrapped(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message.setdefault('headers', []).append((b'x-request-id', request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            route = getattr(scope.get('route'), 'path', 'unmatched')
            method = scope['method'] if scope['method'] in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'} else 'OTHER'
            elapsed = time.perf_counter() - start
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.latency.labels(method, route).observe(elapsed)
            if route not in {'/metrics', '/health/live', '/health/ready'}:
                logging.getLogger('campusguard').info('request', extra={'request_id': request_id, 'route': route,
                    'method': method, 'status': status, 'duration_seconds': round(elapsed, 4)})
