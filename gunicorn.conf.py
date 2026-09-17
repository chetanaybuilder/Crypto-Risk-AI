"""
Gunicorn WSGI Production Server Configuration.

Implements a hybrid worker-thread execution topology (gthread) optimized
for concurrent I/O-bound external API telemetry and background analysis jobs.
"""

import multiprocessing
import os

# Worker topology: scale by CPU count unless overridden by platform concurrency config
_cpu_count = multiprocessing.cpu_count()
workers = int(os.environ.get("WEB_CONCURRENCY", max(2, _cpu_count * 2 + 1)))

# Thread pool per worker for handling concurrent keep-alive HTTP requests
threads = int(os.environ.get("WEB_MAX_THREADS", 4))
worker_class = "gthread"

# Request timeout cap accommodates external provider retry cycles
timeout = 120

# Stream logs directly to stdout/stderr for container log aggregators
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Ingress port binding
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"


def post_fork(server, worker):
    """Lifecycle hook invoked immediately after a worker process is forked."""
    server.log.info(f"Worker spawned (pid: {worker.pid})")
