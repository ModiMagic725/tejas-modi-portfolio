"""
Django settings for portfolio_project.

Ye file local (aapke computer) aur production (Render) dono par chalti hai.
Secret cheezein (password, key) yahan nahi likhte. Wo environment variables se aati hain:
  - Local par: project folder ki `.env` file se
  - Render par: Render dashboard ke "Environment" section se
"""
from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Local par `.env` file padhta hai. Render par `.env` hoti hi nahi, wahan ye line kuch nahi karti.
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


TEMPLATES_MYAPP_DIRS = os.path.join(BASE_DIR / 'portfolio_app/templates')
TEMPLATES_MYAPP1_DIRS = os.path.join(BASE_DIR / 'dashboard_app/templates')


# ---------------------------------------------------------------- Security basics
DEBUG = env_bool('DEBUG', False)           # DEBUG hamesha False rakhte hain, local .env mein True kar lena

# DEBUG=True par bhi apna custom 404 page dikhana hai? False karoge to Django ka peela debug 404 page aayega
CUSTOM_404_IN_DEBUG = env_bool('CUSTOM_404_IN_DEBUG', True)

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'local-development-only-key-not-for-production'
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is not set. "
            "Local par .env file mein SECRET_KEY likho, Render par Environment mein add karo."
        )

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

# Render apna address khud RENDER_EXTERNAL_HOSTNAME naam ke variable mein deta hai
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

if not DEBUG:
    # Render HTTPS ko apne proxy par handle karta hai; ye line Django ko batati hai ki request HTTPS thi
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# ---------------------------------------------------------------- Apps & middleware
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary_storage',
    'cloudinary',
    'portfolio_app',
    'dashboard_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',      # production mein CSS/JS serve karta hai (SecurityMiddleware ke turant baad)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'portfolio_project.errors.Custom404InDebugMiddleware',   # local (DEBUG=True) par bhi custom 404 page dikhata hai
]

ROOT_URLCONF = 'portfolio_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATES_MYAPP_DIRS, TEMPLATES_MYAPP1_DIRS],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'dashboard_app.context_processors.user_context',
                'dashboard_app.context_processors.nav_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'portfolio_project.wsgi.application'


# ---------------------------------------------------------------- Database
# DATABASE_URL set hai to wahi database (Neon), nahi to local db.sqlite3
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=60,
        conn_health_checks=True,
    )
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = False


# ---------------------------------------------------------------- Static files (CSS / JS / icons)
# App ke andar ke `static/` folders Django khud dhoondh leta hai, isliye STATICFILES_DIRS ki zaroorat nahi.
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'      # `collectstatic` saari static files yahan ikatthi karta hai; Whitenoise yahin se dikhata hai


# ---------------------------------------------------------------- Media files (dashboard se upload hone wali files)
# Images Cloudinary par save hoti hain (permanent). CLOUDINARY_URL set na ho to local `media/` folder use hota hai.
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')

if CLOUDINARY_URL:
    CLOUDINARY_STORAGE = {'CLOUDINARY_URL': CLOUDINARY_URL}
    DEFAULT_FILE_BACKEND = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    DEFAULT_FILE_BACKEND = 'django.core.files.storage.FileSystemStorage'

STORAGES = {
    'default': {'BACKEND': DEFAULT_FILE_BACKEND},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}


# ---------------------------------------------------------------- Email
# Local par email terminal mein print hoti hai. Production mein EMAIL_BACKEND environment variable se badlega.
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')

EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
# SMTP connect/read par max itne second ruko (default 'forever' hota hai -> Gunicorn WORKER TIMEOUT -> 502)
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
# Render free plan par SMTP block hota hai -> EMAIL_BACKEND=dashboard_app.email_backends.BrevoAPIEmailBackend set karo (HTTPS API)
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')


# ---------------------------------------------------------------- Public profile links
# Homepage par GitHub icon tabhi dikhta hai jab ye set ho. Render > Environment mein GITHUB_URL add karo
# (ya yahin apna link likh do), e.g. https://github.com/your-username
GITHUB_URL = os.environ.get('GITHUB_URL', 'https://github.com/ModiMagic725')


# ---------------------------------------------------------------- Logging
# Production mein error ki details Render ke "Logs" tab mein dikhein, iske liye ye zaroori hai.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
    },
}