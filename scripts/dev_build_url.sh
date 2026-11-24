#!/usr/bin/env bash
# Print "<wheel url> <sha256>" for the dev build of a branch or commit (see
# .github/workflows/dev-build.yml). Exits 1 if that build isn't published yet.
#
#   scripts/dev_build_url.sh main
#   scripts/dev_build_url.sh 0123abcd4567        # a sha (7-40 hex)
#   read -r url sha < <(scripts/dev_build_url.sh my-branch)
#
# Needs only curl and python3; it sets GH_TOKEN/GITHUB_TOKEN as a bearer token
# if present, to lift the API rate limit. The downloads themselves are anonymous.
set -euo pipefail

repo="${CIVEX_DEV_REPO:-sullivan-james/civex-service}"
ref="${1:?usage: dev_build_url.sh <branch|sha>}"
api="https://api.github.com/repos/$repo"
auth=()
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -n "$token" ]; then auth=(-H "Authorization: Bearer $token"); fi

get() { curl -fsS "${auth[@]}" -H "Accept: ${2:-application/vnd.github+json}" "$1"; }

if [[ "$ref" =~ ^[0-9a-f]{7,40}$ ]]; then
  sha="$ref"
else
  sha="$(get "$api/commits/$ref" application/vnd.github.sha)" \
    || { echo "no such branch: $ref" >&2; exit 1; }
fi
tag="dev-${sha:0:12}"

release="$(get "$api/releases/tags/$tag")" \
  || { echo "no dev build $tag yet (is the Dev build workflow still running?)" >&2; exit 1; }

url="$(python3 -c '
import json, sys
for a in json.load(sys.stdin)["assets"]:
    if a["name"].endswith(".whl"):
        print(a["browser_download_url"]); break
' <<<"$release")"
[ -n "$url" ] || { echo "$tag has no wheel" >&2; exit 1; }

wheel="${url##*/}"
sums="$(curl -fsSL "${url%/*}/SHA256SUMS")"
hash="$(awk -v w="$wheel" '$2 == w || $2 == "*" w {print $1}' <<<"$sums")"
[ -n "$hash" ] || { echo "$tag's SHA256SUMS doesn't list $wheel" >&2; exit 1; }

echo "$url $hash"
