"""LLM runner using mlx-lm.

Why MLX on M-series:
- Unified-memory makes 14B-q4 fit comfortably alongside Whisper + BGE-M3.
- mlx-lm has first-class Apple-Silicon support; no CUDA, no Metal-via-llama.cpp
  juggling.
- Switching models is a string change; we compare options in the eval harness.

Default: mlx-community/Qwen2.5-14B-Instruct-4bit. Strong English output,
reads Gujarati context well in our smoke tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class GenResult:
    text: str
    prompt_tokens: int
    output_tokens: int
    model: str


@lru_cache(maxsize=1)
def _load(model_name: str):
    try:
        from mlx_lm import load
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "mlx-lm is required for LLM inference. Install with: uv sync --extra ml"
        ) from e
    return load(model_name)


def generate(
    *,
    system: str,
    user: str,
    model: str = "mlx-community/Qwen2.5-14B-Instruct-4bit",
    max_new_tokens: int = 512,
    temperature: float = 0.2,
) -> GenResult:
    from mlx_lm import generate as mlx_generate

    tokenizer, model_obj = _load(model)
    # `_load` returns (model, tokenizer) in mlx-lm; some versions reverse it.
    # Detect which is which by looking for `apply_chat_template`.
    if hasattr(model_obj, "apply_chat_template"):
        model_obj, tokenizer = tokenizer, model_obj  # swap

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)

    text = mlx_generate(
        model_obj,
        tokenizer,
        prompt=prompt,
        max_tokens=max_new_tokens,
        temp=temperature,
        verbose=False,
    )

    # mlx_generate returns either a string or a generator depending on version.
    if not isinstance(text, str):
        text = "".join(text)

    return GenResult(
        text=text.strip(),
        prompt_tokens=len(tokenizer.encode(prompt)),
        output_tokens=len(tokenizer.encode(text)),
        model=model,
    )
