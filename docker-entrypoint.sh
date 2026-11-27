#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    groupmod -o -g "$PGID" metashelf
    usermod -o -u "$PUID" metashelf
    mkdir -p "${METASHELF_CONFIG_DIR:-/config}"
    chown -R "${PUID}:${PGID}" "${METASHELF_CONFIG_DIR:-/config}"
    exec gosu metashelf "$@"
fi

exec "$@"
