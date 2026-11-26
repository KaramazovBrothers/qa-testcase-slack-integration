# Runtime image for QAHelper.
#
# One process, no build tools: the frontend bundle in `app/static` is committed,
# and `psycopg[binary]` ships wheels, so the runtime stage needs neither node
# nor gcc. Matches `DEVOPS_TASK.md`: exactly one worker because the Slack reply
# stream (SSE) keeps its subscribers in this process' memory.

FROM python:3.11-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# A self-contained virtualenv. `pip install --prefix` was tried first and places
# the packages where the runtime cannot find them, so the tree is copied whole.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
# Wheels only: if a package ever starts needing a compiler, the build fails here
# loudly instead of producing a slower, unverified image.
RUN pip install --no-warn-script-location -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# `libpq` is not needed: psycopg[binary] bundles its own client library.
RUN groupadd --system --gid 10001 qahelper \
 && useradd --system --uid 10001 --gid qahelper --home-dir /app --shell /usr/sbin/nologin qahelper

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY app ./app

# `config/slack_routes.json` is environment-specific and git-ignored: it is
# copied from a secret/ConfigMap over this directory at run time. Only the
# example ships in the image, and the app falls back to SLACK_CHANNEL_ID when
# the real file is absent.
COPY config/slack_routes.example.json ./config/

# Local usage keeps SQLite in `data/`; in production PostgreSQL is used and this
# directory stays empty. The mount point must exist and be writable.
RUN mkdir -p /app/data && chown -R qahelper:qahelper /app

USER qahelper

EXPOSE 8000

# `GET /` answers 200 only after the schema is ready, so this is a real
# readiness probe and not just "the socket is open".
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# `--no-proxy-headers` is intentionally absent: behind the corporate proxy the
# forwarded headers are required, and the proxy is trusted via
# QAHELPER_ACCESS_MODE=proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
