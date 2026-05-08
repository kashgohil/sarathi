"""Tier-1 question detection: cheap regex heuristics over a single utterance.

Catches the easy cases:
  - English: trailing '?', leading wh-word, modal-fronted ("Can you...").
  - Gujarati: trailing '?', interrogative pronouns (શું/કેમ/ક્યાં/ક્યારે/કોણ/કેટલું),
              and question particles.

Confidence is bounded [0, 1]:
  0.95 — explicit '?' at the end
  0.80 — strong wh / interrogative-pronoun lead
  0.60 — modal-fronted English ("can/could/would/should/will you ...")
  0.40 — Gujarati statement-shaped utterance with embedded interrogative

The LLM tier (qdetect.llm) handles ambiguous cases on the rolling window.
"""

from __future__ import annotations

from dataclasses import dataclass

import regex as re

# English
_EN_WH = re.compile(
    r"\b(what|why|how|when|where|who|whom|whose|which)\b",
    re.IGNORECASE,
)
_EN_MODAL = re.compile(
    r"^\s*(can|could|would|should|will|do|does|did|is|are|am|was|were|may|might)\s+\w+",
    re.IGNORECASE,
)

# Gujarati interrogatives. Stems and full words.
# શું = what, કેમ = why/how, ક્યાં = where, ક્યારે = when, કોણ = who, કેટલું = how much
_GU_INTERROG = re.compile(
    r"(શું|કેમ|ક્યાં|ક્યારે|કોણ|કેટલું|કેટલી|કેટલા|કેવી|કેવો|કેવું)"
)


@dataclass
class HeuristicResult:
    is_question: bool
    confidence: float
    reason: str


def detect_question_heuristic(text: str, lang: str | None = None) -> HeuristicResult:
    if not text or not text.strip():
        return HeuristicResult(False, 0.0, "empty")

    stripped = text.strip()

    # 1. Trailing '?' is the most reliable signal in either language.
    if stripped.endswith("?") or stripped.endswith("？"):
        return HeuristicResult(True, 0.95, "trailing_qmark")

    # 2. Language-specific cues.
    if lang == "gu" or _GU_INTERROG.search(stripped):
        if _GU_INTERROG.search(stripped):
            return HeuristicResult(True, 0.80, "gu_interrogative")

    if lang in (None, "en"):
        # Wh-word at sentence start is strong.
        m = _EN_WH.match(stripped)
        if m:
            return HeuristicResult(True, 0.80, "en_wh_lead")
        # Wh-word anywhere is medium.
        if _EN_WH.search(stripped):
            return HeuristicResult(True, 0.55, "en_wh_embedded")
        # Modal-fronted yes/no question.
        if _EN_MODAL.match(stripped):
            return HeuristicResult(True, 0.60, "en_modal_lead")

    return HeuristicResult(False, 0.0, "no_match")
