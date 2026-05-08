#!/usr/bin/env bash
# Stage the helper binaries into the location Tauri's `externalBin` expects:
# src-tauri/binaries/<name>-<rustc-target-triple>.
#
# Two helpers are staged:
#   1. audio-tap         — built by macos/build.sh
#   2. sarathi-sidecar   — built via PyInstaller (apps/sidecar/sarathi.spec).
#                          If the PyInstaller dist is absent we fall back
#                          to staging a tiny launcher shim that spawns
#                          `uv run sarathi serve`. This keeps `bun tauri:dev`
#                          working without the Python build pipeline.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_TAURI="$(cd "$DIR/.." && pwd)"
REPO_ROOT="$(cd "$SRC_TAURI/../../.." && pwd)"

TARGET="${TAURI_ENV_TARGET_TRIPLE:-${TARGET_TRIPLE:-}}"
if [ -z "$TARGET" ]; then
  TARGET="$(rustc -vV | sed -n 's|host: ||p')"
fi

CONFIG="${1:-release}"

stage_audio_tap() {
  local src="$DIR/.build/$CONFIG/audio-tap"
  if [ ! -x "$src" ]; then
    src="$DIR/.build/apple/Products/$( [ "$CONFIG" = "release" ] && echo Release || echo Debug)/audio-tap"
  fi
  if [ ! -x "$src" ]; then
    echo "audio-tap not built; run macos/build.sh first" >&2
    exit 1
  fi
  local dst="$SRC_TAURI/binaries/audio-tap-$TARGET"
  cp "$src" "$dst"
  chmod +x "$dst"
  echo "staged $dst"
}

stage_sidecar() {
  local sidecar_dist="$REPO_ROOT/apps/sidecar/dist/sarathi-sidecar/sarathi-sidecar"
  local dst="$SRC_TAURI/binaries/sarathi-sidecar-$TARGET"

  if [ -x "$sidecar_dist" ]; then
    cp "$sidecar_dist" "$dst"
    chmod +x "$dst"
    echo "staged $dst (PyInstaller build)"
    return
  fi

  # Fallback: write a shim that defers to `uv run sarathi serve`. Useful for
  # `bun tauri:dev` workflows where you don't need the bundled Python.
  cat > "$dst" <<'SHIM'
#!/usr/bin/env bash
exec uv run --project "$(cd "$(dirname "$0")/../../../sidecar" 2>/dev/null && pwd)" sarathi serve "$@"
SHIM
  chmod +x "$dst"
  echo "staged $dst (uv-run shim — no PyInstaller build found)"
}

mkdir -p "$SRC_TAURI/binaries"
stage_audio_tap
stage_sidecar
