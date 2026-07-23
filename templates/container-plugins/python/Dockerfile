# Starter Dockerfile for a Tier 2 (container) civex plugin written in
# Python.
#
# Build context is this plugin's own directory (_civex/plugins/<name>/,
# alongside civex-plugin.toml) -- civex auto-builds and content-hash-caches
# the image from here, so there's no manual `docker build` step. Copy this
# Dockerfile and plugin.py into a new plugin directory and edit plugin.py;
# civex_plugin_sdk.serve_container (installed below) handles the wire
# protocol, so this Dockerfile itself rarely needs to change.

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir civex-plugin-sdk

COPY . .

ENTRYPOINT ["python", "plugin.py"]
