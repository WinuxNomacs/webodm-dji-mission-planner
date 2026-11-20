#!/usr/bin/env bash
# A WebODM checkout in dev mode, with this repo's plugin mounted (see dev/compose.yml).
#   [MP_NO_KEY=1] dev/webodm.sh up | down | logs [service] | ps | <any docker compose command>
# WebODM 4.0.0: ignored/WebODM, port 8009, livereload 35738, containers mp-webapp, mp-worker, ..., project and
# volumes webodm-mission-planner (the repo's name before it became webodm-dji-mission-planner, kept so the stack
# keeps its data). The plugin supports WebODM 4.0.0 and later only.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

# Each version's images, pinned by digest (the same as webodm-geojson's): a tag can be pushed again, and a local
# `latest` tag can be another build (a fork's). Upgrading: move ignored/WebODM to the new tag, pull its images,
# move the digests here, `dev/webodm.sh up`, run the tests.
case "${MP_WEBODM:=4.0.0}" in
    4.0.0)
        webodm="$repo/ignored/WebODM" project=webodm-mission-planner MP_PREFIX=mp port=8009 livereload=35738
        export MP_WEBAPP_IMAGE=webodm/webodm_webapp@sha256:4572838208348c189fce3bfeabd1eaa08285efd841520ff2f08460611aac14a5
        export MP_DB_IMAGE=webodm/webodm_db@sha256:6d43e32ec24c388c5d5975bf6462d21abd6959af3c43d146a2473c1db4d5019c
        export MP_BROKER_IMAGE=valkey/valkey@sha256:bf09d58e96d6b4524a15396b65b242bbe18beebbcc15a04d8ee75ddac62fae0b
        export MP_NODE_IMAGE=webodm/nodeodx@sha256:f3621054cec0829ff8d94272fa4ec9138621f034135ff9a792fe309bd7d964ad ;;
    *) echo "MP_WEBODM: 4.0.0" >&2; exit 1 ;;
esac
if [ ! -d "$webodm" ]; then
    echo "No WebODM checkout at $webodm (CLAUDE.md, Dev environment, says how to make it)" >&2; exit 1
fi
export MP_PREFIX
export WO_PORT="${WO_PORT:-$port}" MP_LIVERELOAD_PORT="${MP_LIVERELOAD_PORT:-$livereload}"
export WO_HOST=localhost WO_DEBUG=YES WO_DEV=YES WO_BROKER=redis://broker WO_DEFAULT_NODES=1
export WO_MEDIA_DIR=appmedia WO_DB_DIR=dbdata WO_SECRET_KEY="${WO_SECRET_KEY:-}"
# The OpenTopography key: from the environment, else from the repo's .env (ignored by git; only this line is read).
# MP_NO_KEY=1 starts WebODM without one (to check the plugin's settings page, where a key is then saved).
if [ -n "${MP_NO_KEY:-}" ]; then
    WO_OPENTOPOGRAPHY_API_KEY=""
elif [ -z "${WO_OPENTOPOGRAPHY_API_KEY:-}" ] && [ -f "$repo/.env" ]; then
    WO_OPENTOPOGRAPHY_API_KEY="$(sed -n 's/^WO_OPENTOPOGRAPHY_API_KEY=//p' "$repo/.env" | head -n 1 | tr -d '\r"'"'"' ')"
fi
export WO_OPENTOPOGRAPHY_API_KEY="${WO_OPENTOPOGRAPHY_API_KEY:-}"
# MP_PLUGIN_DIR=<empty dir> runs WebODM without the mounted plugin (the release check installs the zip instead)
export MP_PLUGIN_DIR="${MP_PLUGIN_DIR:-$repo/mission_planner}"

compose=(docker compose -p "$project" --project-directory "$webodm"
         -f "$webodm/docker-compose.yml" -f "$webodm/docker-compose.dev.yml" -f "$repo/dev/compose.yml")

case "${1:-}" in
    # New anonymous volumes: the dev compose keeps the image's venv in one, which a new image must not reuse
    up) shift; exec "${compose[@]}" up -d --renew-anon-volumes "$@" ;;
    down) shift; exec "${compose[@]}" down --remove-orphans "$@" ;;
    logs) shift; exec "${compose[@]}" logs -f --tail 100 "$@" ;;
    "") sed -n '2,6p' "$0"; exit 1 ;;
    *) exec "${compose[@]}" "$@" ;;
esac
