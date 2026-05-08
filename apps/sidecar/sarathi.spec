# PyInstaller spec for the Sarathi sidecar.
#
# Produces a single self-contained binary at dist/sarathi-sidecar that the
# Tauri shell can spawn instead of `uv run sarathi serve`. Running:
#
#     uv run --extra ml pyinstaller apps/sidecar/sarathi.spec
#
# from the repo root produces apps/sidecar/dist/sarathi-sidecar/.
#
# Notes
# -----
# - PyInstaller bundles the Python interpreter + stdlib + every imported
#   module. The [ml] extras are *huge* (~3 GB of torch + paddle + mlx). For
#   distribution we ship in `onedir` mode (a folder, not a single binary)
#   so the bundle contents stay browsable; macOS code-signing is also much
#   faster on a directory than on a single 3GB executable.
# - Models themselves are NOT bundled. They download to user_data_dir on
#   first use. This keeps the .app reasonable (~600 MB without [ml],
#   ~3 GB with) and lets us ship version updates without re-downloading
#   the models.
# - We deliberately keep `[ml]` extras optional: shipping the no-ml build
#   produces a ~150 MB sidecar that still does ingest, chunking, retention,
#   and Q&A scaffolding — useful for offline-doc testing without the LLM.

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

import os

block_cipher = None

PROJECT_ROOT = Path(os.environ.get("SARATHI_SIDECAR_ROOT", Path(SPEC).parent)).resolve()
SRC = PROJECT_ROOT / "src" / "sarathi"
CONFIG = PROJECT_ROOT / "config"

# Hidden imports: PyInstaller's static analysis misses lazy/optional imports
# behind try/except RuntimeError, which is exactly how we wrap our [ml] deps.
hiddenimports = [
    # Core
    "sarathi.cli",
    "sarathi.serve",
    "sarathi.pipeline",
    "sarathi.config",
    "sarathi.textproc.normalize",
    "sarathi.textproc.sentence_split",
    "sarathi.textproc.chunk",
    "sarathi.ingest.pdf",
    "sarathi.ingest.lang_id",
    "sarathi.ingest.types",
    "sarathi.qdetect.heuristic",
    "sarathi.qdetect.rolling",
    "sarathi.store.sqlite",
    # Optional [ml] — included if installed at build time, else PyInstaller
    # silently skips them and the runtime stub paths kick in.
    "sarathi.asr.whisper",
    "sarathi.asr.streaming",
    "sarathi.asr.vad",
    "sarathi.asr.diarize",
    "sarathi.embed.bge_m3",
    "sarathi.retrieve.lance_store",
    "sarathi.retrieve.hybrid",
    "sarathi.retrieve.rerank",
    "sarathi.llm.mlx_runner",
    "sarathi.llm.prompt",
    "sarathi.qdetect.llm",
    "sarathi.ingest.ocr",
    # Native lib quirks
    "indicnlp.normalize.indic_normalize",
    "indicnlp.tokenize.sentence_tokenize",
    "regex._regex",
]

datas = [
    (str(CONFIG), "config"),
]

a = Analysis(
    [str(SRC / "cli.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude desktop frameworks PyInstaller often pulls via transitive
        # imports — we don't need them and they bloat the bundle.
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "matplotlib",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sarathi-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX corrupts mach-o signatures
    console=True,          # we read stdout/stderr from the parent
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="sarathi-sidecar",
)
