from pathlib import Path
import os

import dj_database_url


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------
# Core security / environment
# ---------------------------------------------------------------------

# In Railway: set SECRET_KEY as environment variable
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-change-me"
)

# In Railway: set DEBUG=0
DEBUG = os.environ.get("DEBUG", "1") == "1"

# In Railway: set ALLOWED_HOSTS="yourapp.up.railway.app"
# For local dev we allow localhost.
allowed_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
if DEBUG:
    ALLOWED_HOSTS += ["127.0.0.1", "localhost", "*"]

# CSRF: needed for POST requests on Railway domain
# In Railway: set CSRF_TRUSTED_ORIGINS="https://yourapp.up.railway.app"
csrf_env = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_env.split(",") if o.strip()]

# Optional: if behind proxy (common on PaaS) – helps Django detect https
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# ---------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tipping",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # WhiteNoise for static files in production (Railway)
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tippspiel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tipping.context_processors.active_group_context",  # ✅ neu
            ],
        },
    },
]

WSGI_APPLICATION = "tippspiel.wsgi.application"


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------
# Railway provides DATABASE_URL (usually PostgreSQL). Local default: sqlite.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    is_postgres = DATABASE_URL.startswith(("postgres://", "postgresql://"))
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=(is_postgres and (not DEBUG)),
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }



# ---------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------

LANGUAGE_CODE = "de"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]     # <— dein Quell-Ordner
STATIC_ROOT = BASE_DIR / "staticfiles"


# WhiteNoise storage (recommended)
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}


# ---------------------------------------------------------------------
# Auth redirects
# ---------------------------------------------------------------------

LOGIN_REDIRECT_URL = "/tippen/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


# ---------------------------------------------------------------------
# Production hardening (safe defaults)
# ---------------------------------------------------------------------
if not DEBUG:
    # Send cookies only via HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Basic secure headers (optional but recommended)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))  # set >0 when you have HTTPS stable
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"