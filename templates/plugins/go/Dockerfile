# Starter Dockerfile for a civex Tier 2 (container) plugin written in Go.
#
# civex builds this image itself (content-hash-cached from this directory,
# like `uv` caches a venv) and runs it as `docker run -i <image> <mode>` --
# never build or push this manually.
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -o /out/plugin .

# distroless/static: no shell, no package manager -- just the CA certs and
# glibc-compatible /etc/passwd a static Go binary needs. Runs as the built-in
# nonroot user (uid 65532), not root.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/plugin /plugin
ENTRYPOINT ["/plugin"]
