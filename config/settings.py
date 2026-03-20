"""
Django settings for asset_vault project.
Generated for model-layer scaffolding - update secrets, DB, and installed apps before production use.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env(env_path: Path) -> None:
    """Populate os.environ from a simple KEY=VALUE .env file if present."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

# ------- Security (override in environment) -------
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE-ME-before-deploy")
DEBUG = _env_bool("DEBUG", default=True)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

# ------- Applications -------
INSTALLED_APPS = [
    # Django built-ins
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "corsheaders",
    "rest_framework_simplejwt.token_blacklist",

    # Project apps
    "accounts",
    "access",
    "locations",
    "assets",
    "verification",
    "submissions",
    "vendors",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ------- CORS -------
_cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
CORS_ALLOWED_ORIGINS = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081",
    ]
)

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ------- Database -------
# Local development defaults to SQLite so the project runs without a local
# Postgres role/database. Deployed environments can opt into Postgres by
# setting DB_ENGINE=postgresql and the corresponding DB_* variables.
DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()

if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "asset_vault"),
            "USER": os.getenv("DB_USER", "asset_vault"),
            "PASSWORD": os.getenv("DB_PASSWORD", "asset_vault"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ------- Custom user model -------
AUTH_USER_MODEL = "accounts.User"

# ------- Password validation -------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------- Internationalisation -------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ------- Static / Media -------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------- Django REST Framework -------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# ------- SimpleJWT -------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ------- Email -------
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "AssetVault <noreply@vibecopilot.ai>"
)

# Email selection:
# - LOCAL_EMAIL_CONSOLE=true  -> always print OTP mails in terminal
# - LOCAL_EMAIL_CONSOLE=false -> use SMTP when EMAIL_HOST is configured
# - EMAIL_BACKEND             -> explicit override if you want full manual control

# SMTP env vars:
#   EMAIL_BACKEND   – full backend path (optional, auto-detected below)
#   EMAIL_HOST      – SMTP server hostname
#   EMAIL_PORT      – SMTP server port (default 587)
#   EMAIL_HOST_USER – SMTP username / login email
#   EMAIL_HOST_PASSWORD – SMTP password or app-specific password
#   EMAIL_USE_TLS   – "1" or "true" to enable STARTTLS (default True)
#   EMAIL_USE_SSL   – "1" or "true" to enable implicit TLS (default False)
#   EMAIL_TIMEOUT   – connection timeout in seconds (default 10)

_email_host = os.getenv("EMAIL_HOST", "").strip()
_explicit_backend = os.getenv("EMAIL_BACKEND", "").strip()
_local_email_console = _env_bool("LOCAL_EMAIL_CONSOLE", default=DEBUG)

if _explicit_backend:
    EMAIL_BACKEND = _explicit_backend
elif _local_email_console:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
elif _email_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_HOST = _email_host or "localhost"
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1").strip().lower() in ("1", "true", "yes")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "0").strip().lower() in ("1", "true", "yes")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))

# ------- Frontend -------
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:8081")
