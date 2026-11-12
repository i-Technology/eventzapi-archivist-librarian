#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

mkdir -p compose-Y
chmod 700 compose-Y

echo "Starting EventzAPI as UID:GID ${LOCAL_UID}:${LOCAL_GID}"

sudo --preserve-env=LOCAL_UID,LOCAL_GID docker compose up -d
