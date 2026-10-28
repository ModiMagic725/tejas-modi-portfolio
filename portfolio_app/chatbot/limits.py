"""
Rate limiting and the AI spend cap.

Uses Django's cache API, so it needs no new service. The project has no CACHES setting, which
means Django's default per-process memory cache is used. That is fine on Render's free tier
(one small instance) but it has two honest limits: counters reset when the service restarts or
spins down, and each worker process counts separately.

Because of that, treat these as a *safety net*, and set a monthly budget limit in the OpenAI
dashboard as the real hard cap on spending.

Why not reuse dashboard_app.utils.throttled()? It keys on REMOTE_ADDR, which on Render is the
platform proxy's address - the same for every visitor - so it would behave as one shared bucket.
"""
from django.core.cache import cache


def client_key(request):
    """Best-effort visitor identifier.

    Render sits behind Cloudflare, which sets True-Client-IP / CF-Connecting-IP. X-Forwarded-For
    is deliberately NOT used: Render appends to it instead of replacing it, so a visitor could
    spoof it. If neither Cloudflare header is present (local development), REMOTE_ADDR is used.
    """
    for header in ('HTTP_TRUE_CLIENT_IP', 'HTTP_CF_CONNECTING_IP'):
        value = (request.META.get(header) or '').strip()
        if value:
            return value[:64]
    return request.META.get('REMOTE_ADDR') or 'unknown'


def exceeded(scope, ident, limit, window):
    """Count one hit; True when this hit goes over `limit` within `window` seconds."""
    key = f'chatbot:rl:{scope}:{ident}'
    cache.add(key, 0, window)
    try:
        return cache.incr(key) > limit
    except ValueError:                      # key expired between add() and incr()
        cache.set(key, 1, window)
        return False
