"""Prompt construction for the answer LLM.

Design choices:
- Output language is locked to English; LLM may quote Gujarati verbatim.
- Citations are required and must reference the supplied chunk IDs so the
  UI can map back to source + page.
- Refusal is explicit when retrieved context is insufficient — no
  hallucinated answers from prior knowledge.
- Context block is rendered with chunk IDs + (source, page) headers so
  the model can attribute correctly.
"""

from __future__ import annotations

from dataclasses import dataclass


SYSTEM = """\
You are Sarathi, a careful assistant. You help users by answering questions \
based on transcripts of live conversations and uploaded documents.

Rules:
1. Answer in English regardless of the language of the conversation or the documents.
2. When citing documents, quote the relevant Gujarati or English passage verbatim. \
Do not translate or paraphrase the citation text itself.
3. Every claim in your answer must be supported by at least one cited chunk. \
If the retrieved context does not contain enough information, reply with exactly: \
"I don't have enough information in the provided documents to answer that."
4. Cite by chunk id, e.g. "[c3]". Multiple citations OK.
5. Be concise. Do not pad. Do not restate the question.
"""


@dataclass
class ContextChunk:
    chunk_id: str  # short label like "c1", "c2" used by the LLM in citations
    text: str
    source: str
    page: int | None
    lang: str | None


def render_context(chunks: list[ContextChunk]) -> str:
    parts = []
    for ch in chunks:
        head = f"[{ch.chunk_id}] source={ch.source}"
        if ch.page is not None:
            head += f" page={ch.page}"
        if ch.lang:
            head += f" lang={ch.lang}"
        parts.append(f"{head}\n{ch.text}")
    return "\n\n".join(parts)


def build_user_message(
    *,
    question: str,
    transcript: str | None,
    chunks: list[ContextChunk],
) -> str:
    sections = []
    if transcript:
        sections.append(f"### Live transcript (most recent)\n{transcript}")
    sections.append(f"### Retrieved context\n{render_context(chunks)}")
    sections.append(f"### Question\n{question}")
    return "\n\n".join(sections)
