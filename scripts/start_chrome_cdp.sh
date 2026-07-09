#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PROFILE_DIR="${VFS_CHROME_PROFILE:-$PWD/.chrome-profile}"
PORT="${CDP_PORT:-9222}"
ADDRESS="${CDP_ADDRESS:-127.0.0.1}"
ALLOW_ORIGINS="${CDP_ALLOW_ORIGINS:-http://127.0.0.1:$PORT}"

exec "$CHROME" \
  "--remote-debugging-port=$PORT" \
  "--remote-debugging-address=$ADDRESS" \
  "--remote-allow-origins=$ALLOW_ORIGINS" \
  "--user-data-dir=$PROFILE_DIR" \
  --lang=ru-RU \
  --new-window "https://visa.vfsglobal.com/rus/ru/hun/"
