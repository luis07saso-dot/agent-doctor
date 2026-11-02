# Pinned: Python 3.12.16 slim (bookworm), multi-arch index digest.
FROM python:3.12.16-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 doctor
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agent ./agent

# uagents writes <addr>_data.json to the CWD. Keep it on a volume.
RUN mkdir /data && chown doctor:doctor /data
WORKDIR /data
ENV PYTHONPATH=/app

USER doctor
# No secrets in the image. Compose injects .env at runtime.
CMD ["python", "-m", "agent.main"]
