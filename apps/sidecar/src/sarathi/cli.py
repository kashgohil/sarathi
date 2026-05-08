"""Sarathi sidecar CLI.

Subcommands:
  ingest <doc-or-dir>      Ingest one document or a directory; print blocks as JSONL.
  chunk <text-or-path>     Chunk text (debug/inspection helper).
  run --audio --docs       One-shot end-to-end: ingest docs, transcribe audio,
                           retrieve, answer. Stubs for ASR/embed/LLM until M1.
  serve                    Long-running streaming mode (M2 stub).

Output is JSON / NDJSON to stdout so the Tauri side can consume it directly.
Diagnostics go to stderr via `rich`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from sarathi.config import Config, load_config
from sarathi.ingest.lang_id import detect_lang
from sarathi.ingest.pdf import extract_pdf
from sarathi.ingest.types import Block
from sarathi.textproc.chunk import ChunkConfig, chunk_text
from sarathi.textproc.normalize import normalize

app = typer.Typer(
    name="sarathi",
    help="Local-first ML sidecar for Sarathi.",
    no_args_is_help=True,
    add_completion=False,
)

err = Console(stderr=True)


def _emit(obj: dict) -> None:
    """Write a single JSON object to stdout, line-buffered."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _ingest_path(path: Path, *, fasttext_model: str | None) -> Iterable[Block]:
    """Dispatch to the right extractor based on suffix."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        for block in extract_pdf(path):
            if block.text:
                block.lang = detect_lang(block.text, fasttext_model=fasttext_model)
            yield block
    elif suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
        for i, para in enumerate(text.split("\n\n")):
            if not para.strip():
                continue
            yield Block(
                text=para.strip(),
                page=1,
                source=str(path.resolve()),
                block_index=i,
                lang=detect_lang(para, fasttext_model=fasttext_model),
            )
    else:
        err.print(f"[yellow]skipping unsupported file: {path}[/yellow]")


def _resolve_inputs(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(
            p
            for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md"}
        )
    raise typer.BadParameter(f"not a file or directory: {target}")


@app.command()
def ingest(
    target: Path = typer.Argument(..., help="File or directory to ingest."),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Override config TOML."),
):
    """Ingest doc(s) and print one Block per line as JSON."""
    cfg = load_config(config_path)
    fasttext_model = cfg.section("lang_id").get("model_path")  # may be None pre-download

    for path in _resolve_inputs(target):
        for block in _ingest_path(path, fasttext_model=fasttext_model):
            _emit(
                {
                    "type": "block",
                    "text": block.text,
                    "page": block.page,
                    "source": block.source,
                    "block_index": block.block_index,
                    "lang": block.lang,
                    "is_ocr": block.is_ocr,
                    "ocr_confidence": block.ocr_confidence,
                    "bbox": list(block.bbox) if block.bbox else None,
                    "metadata": block.metadata,
                }
            )


@app.command()
def chunk(
    target: str = typer.Argument(..., help="Either inline text or a path to a text file."),
    lang: str = typer.Option("en", "--lang"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Override config TOML."),
):
    """Chunk a string or file. Emits one chunk per line."""
    cfg = load_config(config_path)
    chunk_cfg = _chunk_config_from(cfg)

    p = Path(target)
    text = p.read_text(encoding="utf-8") if p.exists() and p.is_file() else target
    text = normalize(text, lang=lang)

    for c in chunk_text(text, lang=lang, config=chunk_cfg):
        _emit(
            {
                "type": "chunk",
                "text": c.text,
                "token_count": c.token_count,
                "sentence_range": list(c.sentence_range),
                "lang": c.lang,
                "metadata": c.metadata,
            }
        )


def _chunk_config_from(cfg: Config) -> ChunkConfig:
    s = cfg.section("chunk")
    return ChunkConfig(
        target_tokens=s.get("target_tokens", 400),
        max_tokens=s.get("max_tokens", 512),
        overlap_tokens=s.get("overlap_tokens", 50),
        overlap_sentences=s.get("overlap_sentences", 1),
        embed_tokenizer=s.get("embed_tokenizer", "BAAI/bge-m3"),
    )


@app.command()
def run(
    audio: Path = typer.Option(..., "--audio", exists=True, help="Path to audio file."),
    docs: Path = typer.Option(..., "--docs", exists=True, help="Path to docs file or dir."),
    question: Optional[str] = typer.Option(
        None, "--question", help="Optional explicit question; otherwise auto-detected."
    ),
    config_path: Optional[Path] = typer.Option(None, "--config", help="Override config TOML."),
):
    """One-shot end-to-end: ingest → transcribe → retrieve → answer.

    Stages that require the `[ml]` extras (whisper, BGE-M3, MLX, paddle) fall
    back to stubs when those deps aren't installed, so the JSON shape stays
    valid for the eval harness either way. The `stub_stages` field lists what
    fell back so you can see exactly what's wired in.
    """
    from sarathi.pipeline import run as run_pipeline

    cfg = load_config(config_path)
    result = run_pipeline(audio=audio, docs=docs, cfg=cfg, question=question)

    _emit(
        {
            "type": "result",
            "audio": str(audio.resolve()),
            "docs": str(docs.resolve()),
            "question": question,
            "transcript": result.transcript,
            "citations": result.citations,
            "answer": result.answer,
            "chunk_count": result.chunk_count,
            "stub_stages": result.stub_stages,
        }
    )


@app.command()
def serve(
    config_path: Optional[Path] = typer.Option(None, "--config", help="Override config TOML."),
):
    """Long-running streaming mode.

    Reads NDJSON commands from stdin, emits NDJSON events on stdout. See
    `sarathi.serve` module docstring for the wire protocol.
    """
    from sarathi.serve import serve_loop

    cfg = load_config(config_path)
    raise typer.Exit(code=serve_loop(cfg))


if __name__ == "__main__":
    app()
