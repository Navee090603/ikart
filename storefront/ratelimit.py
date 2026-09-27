"""Lightweight per-IP rate limiting backed by Django's cache framework.

Not a substitute for a dedicated library (django-ratelimit/django-axes) under
multi-process/multi-dyno deployments with a shared cache backend, but with
Django's default LocMemCache it still throttles the obvious brute-force and
enumeration cases on a single web process.
"""
from functools import wraps

from django.core.cache import cache
from django.http import HttpResponse


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(key_prefix, limit, period_seconds):
    """Allow at most `limit` requests per client IP per `period_seconds` window."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            cache_key = f"ratelimit:{key_prefix}:{_client_ip(request)}"
            if cache.add(cache_key, 1, timeout=period_seconds):
                count = 1
            else:
                try:
                    count = cache.incr(cache_key)
                except ValueError:
                    cache.set(cache_key, 1, timeout=period_seconds)
                    count = 1
            if count > limit:
                return HttpResponse("Too many requests. Please try again shortly.", status=429)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
