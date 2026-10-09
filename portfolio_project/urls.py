"""
URL configuration for portfolio_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    # path('admin/', admin.site.urls),

    # Public website
    path('', include('portfolio_app.urls')),

    # Dashboard App(For me)
    path('admin-panel/', include('dashboard_app.urls')),

    # Public API + public document routes(Jisse clients mujhko bhejenge sab data)
    path('', include('dashboard_app.public_urls')),
]

# Media & static for development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom 404 pages (portfolio + dashboard) - logic portfolio_project/errors.py mein hai
handler404 = 'portfolio_project.errors.custom_404'
