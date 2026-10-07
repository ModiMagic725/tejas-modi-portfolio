from django.core.cache import cache
from django.utils.text import slugify


def get_ip(request):
    """Client IP. Uses REMOTE_ADDR only; configure your proxy/server to set it correctly."""
    return request.META.get("REMOTE_ADDR") or None


def unique_slug(instance, value, max_length=60):
    base = slugify(value)[:max_length] or "item"
    slug, n = base, 2
    Model = instance.__class__
    while Model.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def throttled(request, scope, limit, window):
    """True when this IP already made `limit` requests for `scope` within `window` seconds."""
    key = f"th:{scope}:{get_ip(request)}"
    cache.add(key, 0, window)
    try:
        return cache.incr(key) > limit
    except ValueError:
        return False