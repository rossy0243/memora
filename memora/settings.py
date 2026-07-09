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

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}

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
    "accounts.apps.AccountsConfig",
    "events.apps.EventsConfig",
    "uploads.apps.UploadsConfig",
    "dashboard.apps.DashboardConfig",
    "core.apps.CoreConfig",
    "processing.apps.ProcessingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "core:home"

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
MEMORA_MAX_UPLOAD_SIZE = int(os.getenv("MEMORA_MAX_UPLOAD_SIZE", str(250 * 1024 * 1024)))
MEMORA_SESSION_UPLOAD_LIMIT = int(os.getenv("MEMORA_SESSION_UPLOAD_LIMIT", "25"))
MEMORA_IP_UPLOAD_LIMIT = int(os.getenv("MEMORA_IP_UPLOAD_LIMIT", "80"))
MEMORA_EVENT_UPLOAD_LIMIT = int(os.getenv("MEMORA_EVENT_UPLOAD_LIMIT", "3000"))
MEMORA_UPLOAD_COOLDOWN_SECONDS = int(os.getenv("MEMORA_UPLOAD_COOLDOWN_SECONDS", "8"))
MEMORA_FFMPEG_BINARY = os.getenv("MEMORA_FFMPEG_BINARY", "ffmpeg")
MEMORA_FFPROBE_BINARY = os.getenv("MEMORA_FFPROBE_BINARY", "ffprobe")
MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS = int(
    os.getenv("MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS", "10")
)
MEMORA_MOVIE_IMAGE_DURATION_SECONDS = int(os.getenv("MEMORA_MOVIE_IMAGE_DURATION_SECONDS", "3"))
MEMORA_MOVIE_VIDEO_MAX_SECONDS = int(os.getenv("MEMORA_MOVIE_VIDEO_MAX_SECONDS", "10"))
MEMORA_MOVIE_MAX_DURATION_SECONDS = int(os.getenv("MEMORA_MOVIE_MAX_DURATION_SECONDS", "300"))
MEMORA_MOVIE_AUTOGENERATE_HOUR = int(os.getenv("MEMORA_MOVIE_AUTOGENERATE_HOUR", "12"))
MEMORA_MOVIE_WIDTH = int(os.getenv("MEMORA_MOVIE_WIDTH", "1280"))
MEMORA_MOVIE_HEIGHT = int(os.getenv("MEMORA_MOVIE_HEIGHT", "720"))
