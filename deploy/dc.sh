#!/usr/bin/env bash
# docker compose wrapper on the VPS. Interpolation vars come from .tag only,
# so the secrets .env is used solely as the container env_file.
cd "$(dirname "$0")" && exec docker compose --env-file .tag "$@"
