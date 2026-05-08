"""Tier-2 question detection: LLM classifier over a rolling window.

Catches what regexes miss:
  - Implicit questions ("I'm not sure how onboarding works for partners.")
  - Cross-utterance questions split across speakers/turns.
  - Statements that imply a need for reference material.

Returns a structured judgment so the host UI can decide whether to act.
The LLM is the same MLX model we use for answer generation — no extra
download cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent

from sarathi.llm.mlx_runner import generate

SYSTEM = dedent(
    """
    You analyze short transcripts from a live conversation and decide whether
    there is an *unresolved question or factual claim* that would benefit from
    looking something up in reference documents.

    Reply with strict JSON, nothing else:
      {"action": "question" | "reference" | "none",
       "query": "<search query in English>",
       "reason": "<one short sentence>"}

    Rules:
    - "question": the speaker is asking something explicit or implicit.
    - "reference": the speaker is making a factual claim that should be verified.
    - "none": small talk, agreement, scheduling, etc.
    - Always emit a "query" — concise, English, suitable for retrieval.
    - Output ONLY the JSON object.
    """
).strip()


@dataclass
class LlmDetect:
    action: str  # "question" | "reference" | "none"
    query: str
    reason: str


def detect_question_llm(
    rolling_text: str,
    *,
    model: str = "mlx-community/Qwen2.5-14B-Instruct-4bit",
    max_new_tokens: int = 120,
) -> LlmDetect:
    if not rolling_text or not rolling_text.strip():
        return LlmDetect(action="none", query="", reason="empty")

    user = f"Transcript window:\n{rolling_text.strip()}"

    try:
        out = generate(
            system=SYSTEM,
            user=user,
            model=model,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
        )
    except RuntimeError:
        return LlmDetect(action="none", query="", reason="llm unavailable")

    text = out.text.strip()
    # Be tolerant of code fences.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block.
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            try:
                parsed = json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                return LlmDetect(action="none", query="", reason="non_json")
        else:
            return LlmDetect(action="none", query="", reason="non_json")

    action = parsed.get("action", "none")
    if action not in ("question", "reference", "none"):
        action = "none"

    return LlmDetect(
        action=action,
        query=parsed.get("query", "") or "",
        reason=parsed.get("reason", "") or "",
    )
