"""
Custom 404 (Page not found) handling.

- /admin-panel/... par galat URL  -> dashboard_app ka "Sorry, Admin" 404 page
- baaki har galat URL             -> portfolio_app ka "Oops!" 404 page

Dono pages galat likha hua URL (request.path) dikhate hain.
"""
from django.conf import settings
from django.shortcuts import render

DASHBOARD_PREFIX = '/admin-panel'


def custom_404(request, exception=None):
    """handler404: DEBUG=False par Django khud ise call karta hai."""
    if request.path.startswith(DASHBOARD_PREFIX):
        return render(request, 'dashboard/404.html', {'page_title': 'Page not found'}, status=404)
    return render(request, '404.html', status=404)


class Custom404InDebugMiddleware:
    """
    DEBUG=True par Django apna peela technical 404 page dikhata hai aur handler404 ko ignore karta hai.
    Ye middleware local par bhi aapka sundar 404 page dikhata hai.
    Django wala debug page wapas chahiye to .env mein CUSTOM_404_IN_DEBUG=False kar do.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            settings.DEBUG
            and getattr(settings, 'CUSTOM_404_IN_DEBUG', True)
            and response.status_code == 404
            and response.get('Content-Type', '').startswith('text/html')
        ):
            return custom_404(request)
        return response
