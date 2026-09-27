# Gunicorn loads this file automatically from the working directory.
import os

# One process keeps the in-memory rate limits and caches accurate (each process would
# otherwise count separately). Threads let requests waiting on Groq, Razorpay, Brevo or
# the database run side by side instead of queuing behind each other.
workers = int(os.environ.get("WEB_CONCURRENCY", 1))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 8))
# Admin CSV imports download product images during the request.
timeout = 60
