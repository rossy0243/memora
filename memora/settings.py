from pathlib import Path
import os
from urllib.parse import unquote, urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    return int(os.getenv(name, str(default)))


def database_from_url(url):
    parsed = urlparse(url)
    engine_by_scheme = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
    }

    return {
        "ENGINE": engine_by_scheme.get(parsed.scheme, "django.db.backends.postgresql"),
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": 600,
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-dev-secret-key")

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storages",
    "accounts.apps.AccountsConfig",
    "events.apps.EventsConfig",
    "uploads.apps.UploadsConfig",
    "dashboard.apps.DashboardConfig",
    "core.apps.CoreConfig",
    "processing.apps.ProcessingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "memora.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "memora.wsgi.application"


DATABASES = {
    "default": database_from_url(
        os.getenv("DATABASE_URL", "postgres://memora:memora@localhost:5432/memora")
    )
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "fr-fr"

TIME_ZONE = "Europe/Paris"

USE_I18N = True

USE_TZ = True


STATIC_URL = os.getenv("DJANGO_STATIC_URL", "/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE_BACKEND = os.getenv("DJANGO_STATICFILES_STORAGE") or (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)

MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / "media"

MEMORA_STORAGE_BACKEND = os.getenv("MEMORA_STORAGE_BACKEND", "local").lower()

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": STATICFILES_STORAGE_BACKEND,
    },
}

if MEMORA_STORAGE_BACKEND == "s3":
    MEMORA_S3_BUCKET_NAME = os.getenv("MEMORA_S3_BUCKET_NAME", "")
    MEMORA_S3_ENDPOINT_URL = os.getenv("MEMORA_S3_ENDPOINT_URL", "") or None
    MEMORA_S3_REGION_NAME = os.getenv("MEMORA_S3_REGION_NAME", "") or None
    MEMORA_S3_CUSTOM_DOMAIN = os.getenv("MEMORA_S3_CUSTOM_DOMAIN", "") or None
    MEMORA_S3_QUERYSTRING_AUTH = env_bool("MEMORA_S3_QUERYSTRING_AUTH", True)

    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "access_key": os.getenv("MEMORA_S3_ACCESS_KEY_ID", ""),
            "secret_key": os.getenv("MEMORA_S3_SECRET_ACCESS_KEY", ""),
            "bucket_name": MEMORA_S3_BUCKET_NAME,
            "endpoint_url": MEMORA_S3_ENDPOINT_URL,
            "region_name": MEMORA_S3_REGION_NAME,
            "custom_domain": MEMORA_S3_CUSTOM_DOMAIN,
            "addressing_style": os.getenv("MEMORA_S3_ADDRESSING_STYLE", "auto"),
            "file_overwrite": False,
            "querystring_auth": MEMORA_S3_QUERYSTRING_AUTH,
            "default_acl": None,
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "core:home"

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_REFERRER_POLICY = os.getenv("DJANGO_SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
X_FRAME_OPTIONS = os.getenv("DJANGO_X_FRAME_OPTIONS", "DENY")

MEMORA_ALLOWED_UPLOAD_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"]
MEMORA_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]
MEMORA_VIDEO_EXTENSIONS = ["mp4", "mov", "webm"]
MEMORA_ALLOWED_UPLOAD_CONTENT_TYPES = {
    "jpg": ["image/jpeg"],
    "jpeg": ["image/jpeg"],
    "png": ["image/png"],
    "webp": ["image/webp"],
    "mp4": ["video/mp4"],
    "mov": ["video/quicktime", "video/mp4"],
    "webm": ["video/webm"],
}
MEMORA_MAX_UPLOAD_SIZE = env_int("MEMORA_MAX_UPLOAD_SIZE", 250 * 1024 * 1024)
MEMORA_SESSION_UPLOAD_LIMIT = env_int("MEMORA_SESSION_UPLOAD_LIMIT", 25)
MEMORA_IP_UPLOAD_LIMIT = env_int("MEMORA_IP_UPLOAD_LIMIT", 80)
MEMORA_EVENT_UPLOAD_LIMIT = env_int("MEMORA_EVENT_UPLOAD_LIMIT", 3000)
MEMORA_UPLOAD_COOLDOWN_SECONDS = env_int("MEMORA_UPLOAD_COOLDOWN_SECONDS", 8)
MEMORA_FFMPEG_BINARY = os.getenv("MEMORA_FFMPEG_BINARY", "ffmpeg")
MEMORA_FFPROBE_BINARY = os.getenv("MEMORA_FFPROBE_BINARY", "ffprobe")
MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS = int(
    os.getenv("MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS", "10")
)
MEMORA_MOVIE_IMAGE_DURATION_SECONDS = env_int("MEMORA_MOVIE_IMAGE_DURATION_SECONDS", 3)
MEMORA_MOVIE_VIDEO_MAX_SECONDS = env_int("MEMORA_MOVIE_VIDEO_MAX_SECONDS", 10)
MEMORA_MOVIE_MAX_DURATION_SECONDS = env_int("MEMORA_MOVIE_MAX_DURATION_SECONDS", 300)
MEMORA_MOVIE_AUTOGENERATE_HOUR = env_int("MEMORA_MOVIE_AUTOGENERATE_HOUR", 12)
MEMORA_MOVIE_VIDEO_ENCODER = os.getenv("MEMORA_MOVIE_VIDEO_ENCODER", "libx264")
MEMORA_MOVIE_WIDTH = env_int("MEMORA_MOVIE_WIDTH", 1280)
MEMORA_MOVIE_HEIGHT = env_int("MEMORA_MOVIE_HEIGHT", 720)
