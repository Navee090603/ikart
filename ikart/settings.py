import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, True))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="change-this-local-development-key")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"],
)

# Lets ops move the admin off the well-known /admin/ path in production
# without a code change (e.g. ADMIN_URL=staff-portal-x7k2/).
ADMIN_URL = env("ADMIN_URL", default="admin/")

SITE_URL = env(
    "SITE_URL",
    default="http://127.0.0.1:8000" if DEBUG else None,
)

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[],
)

if not DEBUG and SECRET_KEY == "change-this-local-development-key":
    raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG=False.")

if not DEBUG and not SITE_URL:
    raise ImproperlyConfigured(
        "SITE_URL environment variable must be set in production (e.g., https://yourdomain.com). "
        "This is used for password reset email links and absolute URLs."
    )

if SITE_URL and not SITE_URL.startswith(("http://", "https://")):
    raise ImproperlyConfigured(
        f"SITE_URL must start with http:// or https://. Got: {SITE_URL}"
    )

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "cloudinary", "cloudinary_storage", "anymail", "storefront",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "storefront.middleware.ContentSecurityPolicyMiddleware",
]
ROOT_URLCONF = "ikart.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages", "storefront.context_processors.cart_summary",
    ]},
}]
WSGI_APPLICATION = "ikart.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    )
}

DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

if "postgresql" in DATABASES["default"].get("ENGINE", ""):
    DATABASES["default"]["OPTIONS"] = {
        "sslmode": "require",
        "connect_timeout": 10,
    }
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "storefront:home"
LOGOUT_REDIRECT_URL = "storefront:home"
# Keep local OTP testing visible in the terminal. Production defaults to Brevo's
# HTTP API (via django-anymail) rather than raw SMTP: Render blocks outbound
# traffic on SMTP ports 25/465/587 for free web services, so smtplib connections
# to any SMTP host (Gmail included) get severed mid-handshake there. EMAIL_BACKEND
# stays overridable via env var for anyone deploying somewhere SMTP isn't blocked.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend" if DEBUG else "anymail.backends.brevo.EmailBackend",
)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="orders@ikart.local")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
ANYMAIL = {
    "BREVO_API_KEY": env("BREVO_API_KEY", default=""),
}

# Cloudinary media storage. Accepts either the single CLOUDINARY_URL
# (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) documented in render.yaml and
# .env.example, or the three separate vars, whichever is set.
CLOUDINARY_CLOUD_NAME = env("CLOUDINARY_CLOUD_NAME", default="")
CLOUDINARY_API_KEY = env("CLOUDINARY_API_KEY", default="")
CLOUDINARY_API_SECRET = env("CLOUDINARY_API_SECRET", default="")

_cloudinary_url = env("CLOUDINARY_URL", default="")
if _cloudinary_url and not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    _parsed = urlparse(_cloudinary_url)
    CLOUDINARY_CLOUD_NAME = CLOUDINARY_CLOUD_NAME or (_parsed.hostname or "")
    CLOUDINARY_API_KEY = CLOUDINARY_API_KEY or (_parsed.username or "")
    CLOUDINARY_API_SECRET = CLOUDINARY_API_SECRET or (_parsed.password or "")

if all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
    STORAGES["default"] = {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    }

    CLOUDINARY_STORAGE = {
        "PREFIX": "",
    }
elif not DEBUG:
    # Render's filesystem is ephemeral: without Cloudinary, uploaded media
    # (product images) would silently disappear on every redeploy.
    raise ImproperlyConfigured(
        "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET must all be set "
        "in production so uploaded media survives redeploys."
    )

# Keys are intentionally optional: checkout supports cash on delivery until a gateway is configured.
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
RAZORPAY_CURRENCY = env("RAZORPAY_CURRENCY", default="INR")
PAYMENT_RESERVATION_MINUTES = env.int("PAYMENT_RESERVATION_MINUTES", default=30)
try:
    TAX_RATE = Decimal(env("TAX_RATE", default="0"))
except InvalidOperation:
    TAX_RATE = Decimal("0")

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Render (and most PaaS platforms) collect whatever goes to stdout/stderr, so
# route everything there rather than to a file nobody will read.
LOG_LEVEL = env("LOG_LEVEL", default="INFO" if not DEBUG else "DEBUG")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "storefront": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
