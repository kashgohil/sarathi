"""Thin wrapper that drives the sidecar CLI as a subprocess.

The eval harness deliberately treats the sidecar as a black box invoked
via its CLI. This keeps the harness usable against future refactors of
the sidecar internals: as long as the JSON shape on stdout is stable,
eval keeps working.

Usage:
    from harness.sidecar_client import run_pipeline, ingest, chunk

The sidecar binary is located via:
  1. `SARATHI_SIDECAR` env var (path to executable), or
  2. `uv run --project apps/sidecar sarathi ...` from repo root.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _sidecar_cmd(*args: str) -> list[str]:
    binary = os.environ.get("SARATHI_SIDECAR")
    if binary:
        return [binary, *args]
    return [
        "uv",
        "run",
        "--project",
        str(REPO_ROOT / "apps" / "sidecar"),
        "sarathi",
        *args,
    ]


def _run(cmd: list[str], *, capture_stderr: bool = True) -> list[dict]:
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr if capture_stderr else ""
        raise RuntimeError(f"sidecar failed (exit {result.returncode}): {msg}")
    out: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def ingest(path: Path) -> list[dict]:
    return _run(_sidecar_cmd("ingest", str(path)))


def chunk(text_or_path: str, lang: str = "en") -> list[dict]:
    return _run(_sidecar_cmd("chunk", text_or_path, "--lang", lang))


def run_pipeline(audio: Path, docs: Path, question: str | None = None) -> dict:
    args = ["run", "--audio", str(audio), "--docs", str(docs)]
    if question:
        args += ["--question", question]
    events = _run(_sidecar_cmd(*args))
    # `run` emits a single result event.
    for e in events:
        if e.get("type") == "result":
            return e
    raise RuntimeError("sidecar did not emit a result event")
