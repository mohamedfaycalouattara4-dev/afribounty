FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

WORKDIR /app

RUN addgroup --system --gid 10001 afribounty \
    && adduser --system --uid 10001 --gid 10001 --no-create-home afribounty

COPY requirements.lock requirements-dev.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY . .
RUN rm -f afribounty.sqlite3 \
    && mkdir -p /app/staticfiles /app/local_secure_evidence \
    && DJANGO_SETTINGS_MODULE=config.settings.development python manage.py collectstatic --noinput \
    && chown -R afribounty:afribounty /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live/', timeout=3)" || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "60", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "--no-sendfile"]
