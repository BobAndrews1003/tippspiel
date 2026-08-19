from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

from django.utils.csp import CSP


# ============================================================
# Hilfsfunktionen
# ============================================================

def env_list(name: str) -> list[str]:
    """
    Liest eine durch Kommas getrennte Umgebungsvariable
    als bereinigte Liste ein.
    """
    value = os.environ.get(name, "")

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def env_bool(
    name: str,
    default: bool = False,
) -> bool:
    """
    Akzeptiert Werte wie:
    1, true, yes und on.
    """
    default_value = "1" if default else "0"

    return (
        os.environ
        .get(name, default_value)
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )


def env_int(
    name: str,
    default: int,
) -> int:
    """
    Liest eine Ganzzahl aus einer Umgebungsvariable.
    """
    raw_value = os.environ.get(
        name,
        str(default),
    ).strip()

    try:
        return int(raw_value)

    except ValueError as exc:
        raise RuntimeError(
            f"{name} muss eine ganze Zahl sein."
        ) from exc


# ============================================================
# Basisverzeichnis
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Lokale Entwicklung kann eine nicht versionierte .env-Datei
# verwenden. Bereits gesetzte Umgebungsvariablen haben Vorrang.
load_dotenv(
    BASE_DIR / ".env",
    override=False,
)


# ============================================================
# Umgebung und zentrale Sicherheitswerte
# ============================================================

# Sicherer Standard:
# Ohne ausdrückliche Umgebungsvariable wird DEBUG nicht aktiviert.
DEBUG = env_bool(
    "DEBUG",
    default=False,
)

# Railway stellt diese Variable automatisch bereit.
ON_RAILWAY = bool(
    os.environ.get("RAILWAY_ENVIRONMENT_ID")
)


# Dieser Schlüssel darf nur lokal verwendet werden.
DEV_SECRET_KEY = (
    "django-insecure-dev-only-change-me"
)

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    DEV_SECRET_KEY,
).strip()


# Verhindert einen Produktionsstart mit einem schwachen
# oder versehentlich veröffentlichten Schlüssel.
if not DEBUG:

    if SECRET_KEY == DEV_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY muss in der "
            "Produktionsumgebung gesetzt werden."
        )

    if (
        len(SECRET_KEY) < 50
        or len(set(SECRET_KEY)) < 5
        or SECRET_KEY.startswith(
            "django-insecure-"
        )
    ):
        raise RuntimeError(
            "SECRET_KEY muss mindestens 50 Zeichen "
            "lang, ausreichend zufällig und ohne "
            "'django-insecure-' Präfix sein."
        )


# ============================================================
# Hosts und CSRF
# ============================================================

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS"
)


if DEBUG:
    ALLOWED_HOSTS.extend(
        [
            "127.0.0.1",
            "localhost",
        ]
    )


# Duplikate entfernen, Reihenfolge beibehalten.
ALLOWED_HOSTS = list(
    dict.fromkeys(ALLOWED_HOSTS)
)


if not DEBUG and not ALLOWED_HOSTS:
    raise RuntimeError(
        "ALLOWED_HOSTS muss in der "
        "Produktionsumgebung gesetzt werden."
    )


CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS"
)


# In Produktion keine unverschlüsselten vertrauenswürdigen
# Ursprünge zulassen.
if not DEBUG:

    invalid_csrf_origins = [
        origin
        for origin in CSRF_TRUSTED_ORIGINS
        if not origin.startswith(
            "https://"
        )
    ]

    if invalid_csrf_origins:
        raise RuntimeError(
            "CSRF_TRUSTED_ORIGINS darf in "
            "Produktion nur HTTPS-Ursprünge "
            "enthalten."
        )


# Nur aktivieren, wenn der Hosting-Proxy den Header
# zuverlässig selbst setzt und fremde Werte entfernt.
if env_bool(
    "TRUST_X_FORWARDED_PROTO",
    default=ON_RAILWAY,
):
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )


# Hostnamen weiterhin über ALLOWED_HOSTS prüfen.
USE_X_FORWARDED_HOST = False


# ============================================================
# Installierte Anwendungen
# ============================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # django-allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",

    # Eigene Anwendung
    "tipping.apps.TippingConfig",
]


# ============================================================
# Middleware
# ============================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",

    # WhiteNoise direkt nach SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    (
        "django.contrib.auth.middleware."
        "AuthenticationMiddleware"
    ),

    (
        "django.contrib.messages.middleware."
        "MessageMiddleware"
    ),

    # django-allauth
    "allauth.account.middleware.AccountMiddleware",

    (
        "django.middleware.clickjacking."
        "XFrameOptionsMiddleware"
    ),
]


ROOT_URLCONF = "tippspiel.urls"


# ============================================================
# Templates
# ============================================================

TEMPLATES = [
    {
        "BACKEND": (
            "django.template.backends.django."
            "DjangoTemplates"
        ),

        "DIRS": [
            BASE_DIR / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                (
                    "django.template."
                    "context_processors.request"
                ),
                (
                    "django.contrib.auth."
                    "context_processors.auth"
                ),
                (
                    "django.contrib.messages."
                    "context_processors.messages"
                ),
                (
                    "tipping.context_processors."
                    "active_group_context"
                ),
            ],
        },
    },
]


WSGI_APPLICATION = "tippspiel.wsgi.application"


# ============================================================
# Authentifizierungs-Backends
# ============================================================

AUTHENTICATION_BACKENDS = [
    # Django-Login und Django-Admin
    (
        "django.contrib.auth.backends."
        "ModelBackend"
    ),

    # django-allauth
    (
        "allauth.account.auth_backends."
        "AuthenticationBackend"
    ),
]


# ============================================================
# Datenbank
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


# In Produktion niemals still auf SQLite zurückfallen.
if not DEBUG and not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL muss in der "
        "Produktionsumgebung gesetzt werden."
    )


if DATABASE_URL:

    is_postgres = DATABASE_URL.startswith(
        (
            "postgres://",
            "postgresql://",
        )
    )

    if not DEBUG and not is_postgres:
        raise RuntimeError(
            "In Produktion wird eine "
            "PostgreSQL-Datenbank erwartet."
        )

    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,

            conn_max_age=env_int(
                "DATABASE_CONN_MAX_AGE",
                600,
            ),

            conn_health_checks=True,

            # Kann bei einem internen, bereits geschützten
            # Datenbanknetzwerk notfalls deaktiviert werden.
            ssl_require=env_bool(
                "DATABASE_SSL_REQUIRED",
                default=not DEBUG,
            ),
        )
    }


else:
    # Nur für lokale Entwicklung.
    DATABASES = {
        "default": {
            "ENGINE": (
                "django.db.backends.sqlite3"
            ),
            "NAME": (
                BASE_DIR / "db.sqlite3"
            ),
        }
    }


# ============================================================
# Cache
# ============================================================

REDIS_URL = os.environ.get(
    "REDIS_URL",
    "",
).strip()


# Allauth verwendet den Django-Cache unter anderem für
# Rate-Limits. In Produktion darf deshalb kein prozesslokaler
# LocMemCache verwendet werden.
if not DEBUG and not REDIS_URL:
    raise RuntimeError(
        "REDIS_URL muss in der "
        "Produktionsumgebung gesetzt werden."
    )


if REDIS_URL:
    # Gemeinsamer Cache für mehrere Serverprozesse.
    # Dafür muss das Python-Paket "redis" installiert sein.
    CACHES = {
        "default": {
            "BACKEND": (
                "django.core.cache.backends.redis."
                "RedisCache"
            ),

            "LOCATION": REDIS_URL,

            "KEY_PREFIX": os.environ.get(
                "CACHE_KEY_PREFIX",
                "catoliga",
            ),

            "TIMEOUT": 300,
        }
    }


else:
    # Für Entwicklung und kleine Testinstallationen.
    # Dieser Cache wird nicht zwischen mehreren Workern geteilt.
    CACHES = {
        "default": {
            "BACKEND": (
                "django.core.cache.backends.locmem."
                "LocMemCache"
            ),

            "LOCATION": (
                "catoliga-local-cache"
            ),

            "TIMEOUT": 300,
        }
    }


# ============================================================
# Passwortvalidierung
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth."
            "password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth."
            "password_validation."
            "MinimumLengthValidator"
        ),
        "OPTIONS": {
            "min_length": 12,
        },
    },
    {
        "NAME": (
            "django.contrib.auth."
            "password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth."
            "password_validation."
            "NumericPasswordValidator"
        )
    },
]


# ============================================================
# Sprache und Zeitzone
# ============================================================

LANGUAGE_CODE = "es"

LANGUAGES = [
    (
        "es",
        "Español",
    ),
]

TIME_ZONE = "America/Guayaquil"

USE_I18N = True

USE_TZ = True


# ============================================================
# Statische Dateien
# ============================================================

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = (
    BASE_DIR / "staticfiles"
)


# ============================================================
# Hochgeladene Mediendateien
# ============================================================

MEDIA_URL = "/media/"

MEDIA_ROOT = Path(
    os.environ.get(
        "MEDIA_ROOT",
        str(
            BASE_DIR / "media"
        ),
    )
)


FILE_UPLOAD_PERMISSIONS = 0o640

FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750


# Begrenzung der Anzahl hochgeladener Dateien.
# Die maximale Avatargröße muss zusätzlich in forms.py
# und möglichst beim Hosting-Proxy geprüft werden.
DATA_UPLOAD_MAX_NUMBER_FILES = env_int(
    "DATA_UPLOAD_MAX_NUMBER_FILES",
    5,
)


DATA_UPLOAD_MAX_NUMBER_FIELDS = env_int(
    "DATA_UPLOAD_MAX_NUMBER_FIELDS",
    1000,
)


# ============================================================
# Datei- und Static-Storage
# ============================================================

STORAGES = {
    # Benutzer-Uploads wie Avatare.
    "default": {
        "BACKEND": (
            "django.core.files.storage."
            "FileSystemStorage"
        ),
    },

    # Lokal einfache statische Speicherung,
    # in Produktion WhiteNoise mit Manifest.
    "staticfiles": {
        "BACKEND": (
            (
                "django.contrib.staticfiles."
                "storage.StaticFilesStorage"
            )
            if DEBUG
            else
            (
                "whitenoise.storage."
                "CompressedManifestStaticFilesStorage"
            )
        ),
    },
}


# ============================================================
# E-Mail
# ============================================================

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    (
        (
            "django.core.mail.backends.console."
            "EmailBackend"
        )
        if DEBUG
        else
        (
            "django.core.mail.backends.smtp."
            "EmailBackend"
        )
    ),
).strip()


EMAIL_HOST = os.environ.get(
    "EMAIL_HOST",
    "",
).strip()


EMAIL_PORT = env_int(
    "EMAIL_PORT",
    587,
)


EMAIL_HOST_USER = os.environ.get(
    "EMAIL_HOST_USER",
    "",
).strip()


EMAIL_HOST_PASSWORD = os.environ.get(
    "EMAIL_HOST_PASSWORD",
    "",
)


EMAIL_USE_TLS = env_bool(
    "EMAIL_USE_TLS",
    default=not DEBUG,
)


EMAIL_USE_SSL = env_bool(
    "EMAIL_USE_SSL",
    default=False,
)


EMAIL_TIMEOUT = env_int(
    "EMAIL_TIMEOUT",
    10,
)


DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "Puntero <noreply@localhost>",
).strip()


SERVER_EMAIL = os.environ.get(
    "SERVER_EMAIL",
    DEFAULT_FROM_EMAIL,
).strip()


if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError(
        "EMAIL_USE_TLS und EMAIL_USE_SSL "
        "dürfen nicht gleichzeitig aktiviert sein."
    )


# ============================================================
# Authentifizierung und django-allauth
# ============================================================

LOGIN_URL = "account_login"

LOGIN_REDIRECT_URL = "dashboard"

LOGOUT_REDIRECT_URL = "account_login"


# Anmeldung über Benutzername oder E-Mail-Adresse.
ACCOUNT_LOGIN_METHODS = {
    "username",
    "email",
}


ACCOUNT_SIGNUP_FIELDS = [
    "username*",
    "email*",
    "password1*",
    "password2*",
]


ACCOUNT_SIGNUP_REDIRECT_URL = (
    "join_group"
)


# Nutzer können genau eine E-Mail-Adresse verwalten
# und diese über einen Bestätigungsprozess ersetzen.
ACCOUNT_CHANGE_EMAIL = True


ACCOUNT_UNIQUE_EMAIL = True


# Lokal keine Bestätigungsmails.
# In Produktion ist E-Mail-Verifizierung verpflichtend.
ACCOUNT_EMAIL_VERIFICATION = os.environ.get(
    "ACCOUNT_EMAIL_VERIFICATION",
    (
        "none"
        if DEBUG
        else
        "mandatory"
    ),
).strip().lower()


if ACCOUNT_EMAIL_VERIFICATION not in {
    "none",
    "optional",
    "mandatory",
}:
    raise RuntimeError(
        "ACCOUNT_EMAIL_VERIFICATION muss "
        "'none', 'optional' oder 'mandatory' sein."
    )


# Erschwert das Ermitteln existierender Accounts.
ACCOUNT_PREVENT_ENUMERATION = True


# Vor sensiblen Kontoänderungen Passwort erneut abfragen.
ACCOUNT_REAUTHENTICATION_REQUIRED = True

ACCOUNT_REAUTHENTICATION_TIMEOUT = 300


# Sitzung nicht dauerhaft über den Browser-Neustart merken.
ACCOUNT_SESSION_REMEMBER = False


# Abmelden nur über POST, nicht über einen einfachen GET-Link.
ACCOUNT_LOGOUT_ON_GET = False


# Eine Bestätigungsmail wird nicht bereits durch einen
# bloßen Linkaufruf bestätigt.
ACCOUNT_CONFIRM_EMAIL_ON_GET = False


# Nach Passwort-Reset nicht automatisch einloggen.
ACCOUNT_LOGIN_ON_PASSWORD_RESET = False


ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3


ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_RESEND = True

ACCOUNT_EMAIL_VERIFICATION_SUPPORTS_CHANGE = False


# Sicherheitsbenachrichtigungen bei Kontoänderungen.
ACCOUNT_EMAIL_NOTIFICATIONS = env_bool(
    "ACCOUNT_EMAIL_NOTIFICATIONS",
    default=not DEBUG,
)


# Einfache zusätzliche Bot-Falle bei der Registrierung.
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = (
    "phone_number"
)


ACCOUNT_USERNAME_MIN_LENGTH = 3


# Proxy-Informationen werden standardmäßig nicht vertraut.
# Erst passend zur echten Hostingarchitektur konfigurieren.
ALLAUTH_TRUSTED_PROXY_COUNT = env_int(
    "ALLAUTH_TRUSTED_PROXY_COUNT",
    0,
)


ALLAUTH_TRUSTED_CLIENT_IP_HEADER = (
    os.environ.get(
        "ALLAUTH_TRUSTED_CLIENT_IP_HEADER",
        (
            "X-Real-IP"
            if ON_RAILWAY
            else ""
        ),
    ).strip()
    or None
)


# Bei verpflichtender Verifizierung darf Produktion
# nicht ohne funktionierende Mailkonfiguration starten.
if (
    not DEBUG
    and ACCOUNT_EMAIL_VERIFICATION
    == "mandatory"
):

    if not os.environ.get(
        "DEFAULT_FROM_EMAIL",
        "",
    ).strip():
        raise RuntimeError(
            "DEFAULT_FROM_EMAIL muss in Produktion "
            "für die E-Mail-Bestätigung gesetzt werden."
        )

    if (
        EMAIL_BACKEND
        == (
            "django.core.mail.backends.smtp."
            "EmailBackend"
        )
        and not EMAIL_HOST
    ):
        raise RuntimeError(
            "EMAIL_HOST muss für das SMTP-Backend "
            "in Produktion gesetzt werden."
        )


# ============================================================
# Allgemeine Django-Einstellungen
# ============================================================

DEFAULT_AUTO_FIELD = (
    "django.db.models.BigAutoField"
)


# ============================================================
# Sitzungen, Cookies und Sicherheitsheader
# ============================================================


# ============================================================
# Content Security Policy
# ============================================================

# Zunächst nur Report-Only:
# Verstöße werden gemeldet, Inhalte aber noch nicht blockiert.
SECURE_CSP_REPORT_ONLY = {
    "default-src": [
        CSP.SELF,
    ],
    "base-uri": [
        CSP.SELF,
    ],
    "form-action": [
        CSP.SELF,
    ],
    "frame-ancestors": [
        CSP.NONE,
    ],
    "object-src": [
        CSP.NONE,
    ],
    "script-src": [
        CSP.SELF,
    ],
    "style-src": [
        CSP.SELF,
    ],
    "img-src": [
        CSP.SELF,
        "data:",
    ],
    "font-src": [
        CSP.SELF,
    ],
    "connect-src": [
        CSP.SELF,
    ],
}

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = "Lax"

CSRF_COOKIE_SAMESITE = "Lax"


# Die App darf nicht in fremde Frames eingebettet werden.
X_FRAME_OPTIONS = "DENY"


SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_REFERRER_POLICY = "same-origin"

SECURE_CROSS_ORIGIN_OPENER_POLICY = (
    "same-origin"
)


# ============================================================
# Produktionssicherheit
# ============================================================

if not DEBUG:

    SESSION_COOKIE_SECURE = True

    CSRF_COOKIE_SECURE = True


    SECURE_SSL_REDIRECT = env_bool(
        "SECURE_SSL_REDIRECT",
        default=True,
    )


    # Anfangs bewusst nur eine Stunde.
    # Nach erfolgreichem Produktionstest kann der Wert
    # schrittweise erhöht werden.
    SECURE_HSTS_SECONDS = env_int(
        "SECURE_HSTS_SECONDS",
        3600,
    )


    # Erst aktivieren, wenn wirklich sämtliche Subdomains
    # ausschließlich HTTPS verwenden.
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "SECURE_HSTS_INCLUDE_SUBDOMAINS",
        default=False,
    )


    # Nicht voreilig aktivieren.
    SECURE_HSTS_PRELOAD = env_bool(
        "SECURE_HSTS_PRELOAD",
        default=False,
    )


else:

    SESSION_COOKIE_SECURE = False

    CSRF_COOKIE_SECURE = False

    SECURE_SSL_REDIRECT = False

    SECURE_HSTS_SECONDS = 0

    SECURE_HSTS_INCLUDE_SUBDOMAINS = False

    SECURE_HSTS_PRELOAD = False


# ============================================================
# Logging
# ============================================================

LOG_LEVEL = os.environ.get(
    "LOG_LEVEL",
    (
        "DEBUG"
        if DEBUG
        else
        "INFO"
    ),
).strip().upper()


LOGGING = {
    "version": 1,

    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": (
                "{levelname} {asctime} "
                "{name}: {message}"
            ),
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": (
                "logging.StreamHandler"
            ),
            "formatter": "standard",
        },
    },

    "root": {
        "handlers": [
            "console",
        ],
        "level": LOG_LEVEL,
    },

    "loggers": {
        "django.security": {
            "handlers": [
                "console",
            ],
            "level": "WARNING",
            "propagate": False,
        },

        "tipping": {
            "handlers": [
                "console",
            ],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

CSRF_FAILURE_VIEW = "tipping.error_views.csrf_failure"
