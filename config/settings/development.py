from .base import *  # noqa: F403

DEBUG = env("DJANGO_DEBUG", "1") == "1"  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
