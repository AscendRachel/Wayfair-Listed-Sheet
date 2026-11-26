# Wayfair Catalog, production image.
# Same Python as the version it was tested on, packages pinned in constraints.txt, runs as a normal user (not root).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata: the app stamps times with the server's clock, so the container must know the local time zone (set TZ).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --create-home app \
 && mkdir /data && chown app:app /data

WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY app ./app
COPY web ./web
COPY run.py VERSION ./

# GT_PORT is the port INSIDE the container (any value works; the proxy is told the same number).
ENV GT_DATA=/data GT_HOST=0.0.0.0 GT_PORT=8000 TZ=America/New_York
USER app
VOLUME /data
EXPOSE 8000

# Asked with bash itself, not a new Python: starting Python every 30 s in each app took a noticeable share of a small
# server's CPU when several apps run side by side.
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD ["bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/${GT_PORT:-8000} && printf 'GET /api/ping HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n' >&3 && timeout 4 head -n 1 <&3 | grep -q ' 200 '"]

# One process on purpose: the database is a single SQLite file, so never run several copies against the same /data.
CMD ["python", "run.py"]
