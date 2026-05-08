#!/usr/bin/env bash
# Build the audio-tap helper. Run from anywhere; uses the directory of this
# script as the Swift package root.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

CONFIG="${1:-release}"
swift build -c "$CONFIG"

OUT="$DIR/.build/$([ "$CONFIG" = "release" ] && echo apple/Products/Release || echo apple/Products/Debug)/audio-tap"
if [ ! -x "$OUT" ]; then
  # Older swift toolchains use a different layout.
  OUT="$DIR/.build/$CONFIG/audio-tap"
fi

echo "$OUT"
