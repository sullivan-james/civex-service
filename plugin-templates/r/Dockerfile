# Starter Dockerfile for an R-language container-tier (Tier 2) civex plugin.
# Copy this whole directory to _civex/plugins/<name>/ alongside
# civex-plugin.toml, then edit plugin.R's invoke() to taste.
#
# Pinned to a specific R point release for reproducible builds -- bump this
# when the team upgrades R.
FROM r-base:4.4.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends r-cran-jsonlite \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY plugin.R entrypoint.sh ./
RUN chmod +x entrypoint.sh

# docker run -i <image> <mode> runs `entrypoint.sh <mode>`, where <mode> is
# "describe" or "run" -- see entrypoint.sh and plugin.R for the wire
# protocol both modes speak over stdin/stdout.
ENTRYPOINT ["./entrypoint.sh"]
