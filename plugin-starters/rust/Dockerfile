# Starter Dockerfile for a civex Tier 2 (container) plugin written in Rust.
#
# civex auto-builds and content-hash-caches an image from this directory --
# there's no manual `docker build` step. The host later runs it as
# `docker run -i <image> describe` / `docker run -i <image> run`, speaking
# newline-delimited JSON over stdin/stdout (see src/protocol.rs).

FROM rust:1-slim-bookworm AS builder
WORKDIR /build
COPY Cargo.toml Cargo.lock* ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
RUN useradd --system --no-create-home plugin
COPY --from=builder /build/target/release/civex-plugin /usr/local/bin/civex-plugin
USER plugin
ENTRYPOINT ["/usr/local/bin/civex-plugin"]
