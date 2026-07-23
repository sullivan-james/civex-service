# syntax=docker/dockerfile:1
#
# Starter Dockerfile for a Tier 2 (container) Java plugin. Build context is
# this directory (see civex-plugin.toml) -- no other paths are referenced.
#
# Multi-stage: compile with a full JDK, ship only the JRE + compiled classes
# so the image civex caches/runs is small.

FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /build
COPY Main.java .
RUN javac -d /build/out Main.java

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /build/out/ /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# `docker run -i <image> <mode>` -- <mode> ("describe" or "run") is passed
# through as the container's command and forwarded to Main by entrypoint.sh.
ENTRYPOINT ["/app/entrypoint.sh"]
