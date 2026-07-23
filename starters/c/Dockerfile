# Starter Dockerfile for a Tier 2 (container) civex plugin written in C.
#
# Multi-stage build: compile the shim + plugin logic with gcc in a
# throwaway builder stage, then copy just the resulting binary into a
# minimal runtime image. The host builds this image from the plugin's own
# directory (content-hash-cached, no manual `docker build`) and runs it as
# `docker run -i <image> <mode>`, where <mode> is "describe" or "run" --
# see src/shim.c for the dispatch and README.md for the wire protocol.
#
# Copy this whole directory into `_civex/plugins/<your_plugin_name>/` and
# edit src/plugin.c (plus civex-plugin.toml) to build your own plugin --
# this Dockerfile shouldn't need to change for most plugins.

FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY src/ src/
RUN gcc -O2 -Wall -Wextra -std=c11 -o plugin src/json.c src/shim.c src/plugin.c -lm

FROM debian:bookworm-slim
COPY --from=builder /build/plugin /app/plugin
ENTRYPOINT ["/app/plugin"]
