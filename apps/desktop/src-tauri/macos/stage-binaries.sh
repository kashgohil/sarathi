#!/usr/bin/env bash
# Stage the built audio-tap helper into the location Tauri's `externalBin`
# expects: src-tauri/binaries/audio-tap-<rustc-target-triple>.
#
# Tauri 2.x requires per-triple binaries so it can pick the right one for
# whichever architecture is being bundled. On Apple Silicon dev machines this
# is `aarch64-apple-darwin`; CI building both arches stages two files.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_TAURI="$(cd "$DIR/.." && pwd)"

TARGET="${TAURI_ENV_TARGET_TRIPLE:-${TARGET_TRIPLE:-}}"
if [ -z "$TARGET" ]; then
  TARGET="$(rustc -vV | sed -n 's|host: ||p')"
fi

CONFIG="${1:-release}"
SRC="$DIR/.build/$CONFIG/audio-tap"
if [ ! -x "$SRC" ]; then
  SRC="$DIR/.build/apple/Products/$( [ "$CONFIG" = "release" ] && echo Release || echo Debug)/audio-tap"
fi
if [ ! -x "$SRC" ]; then
  echo "audio-tap not built; run macos/build.sh first" >&2
  exit 1
fi

DST_DIR="$SRC_TAURI/binaries"
mkdir -p "$DST_DIR"
DST="$DST_DIR/audio-tap-$TARGET"
cp "$SRC" "$DST"
chmod +x "$DST"
echo "staged $DST"
