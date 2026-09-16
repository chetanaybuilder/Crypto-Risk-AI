import multiprocessing
import os

# Calculate optimal workers (usually 2 * CPU + 1, but we limit to available memory on free/hobby tiers)
# If WEB_CONCURRENCY is provided by Render, use it, else default to CPU heuristic
_cpu_count = multiprocessing.cpu_count()
workers = int(os.environ.get("WEB_CONCURRENCY", max(2, _cpu_count * 2 + 1)))

# Use threads for I/O bound tasks
threads = int(os.environ.get("WEB_MAX_THREADS", 4))
worker_class = 'gthread'

# Timeout needs to be high enough for Gemini and CoinGecko API calls
timeout = 120

# Logging configuration
accesslog = "-"  # log to stdout
errorlog = "-"   # log to stderr
loglevel = os.environ.get("LOG_LEVEL", "info")

# Bind address
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")
