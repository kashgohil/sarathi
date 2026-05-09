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

  # Fallback: write a shim that defers to either the venv's Python (if
  # `uv sync` has been run) or `uv run` (if uv is on PATH). The path to
  # apps/sidecar is baked in at staging time — `dirname $0` would break
  # the moment Tauri's `externalBin` mechanism copies this file out of
  # `binaries/` into `target/<profile>/` for dev use.
  local sidecar_abs
  sidecar_abs="$(cd "$REPO_ROOT/apps/sidecar" && pwd)"

  cat > "$dst" <<SHIM
#!/usr/bin/env bash
SIDECAR_DIR="$sidecar_abs"
VENV_PY="\$SIDECAR_DIR/.venv/bin/python"
if [ -x "\$VENV_PY" ]; then
  exec "\$VENV_PY" -m sarathi.cli serve "\$@"
fi
exec uv run --project "\$SIDECAR_DIR" sarathi serve "\$@"
SHIM
  chmod +x "$dst"
  echo "staged $dst (dev shim — sidecar at $sidecar_abs)"
}

mkdir -p "$SRC_TAURI/binaries"
stage_audio_tap
stage_sidecar
