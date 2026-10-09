from django.templatetags.static import static
from django.urls import path
from django.views.generic import RedirectView
from portfolio_app.views import *

urlpatterns = [

    path('',   homepage, name='home'),
    path('about/',   about, name='about'),
    path('websites/',   frontend_work, name='frontend_work'),
    path('backend-projects/',   backend_projects, name='backend_projects'),
    path('contact/',   contact, name='contact'),
    path('start-a-project/',   start_a_project, name='start_a_project'),

    # Browsers aksar /favicon.ico seedha maangte hain - isse har page par favicon dikhta hai
    path('favicon.ico', RedirectView.as_view(url=static('assets/favicon/favicon.ico'), permanent=True)),

]
