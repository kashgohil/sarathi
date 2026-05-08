"""Rolling transcript window for proactive retrieval and LLM-tier qdetect.

Holds the most recent utterances within a time budget. Used to:
  - Provide context to the question detector.
  - Build the retrieval query for proactive references.
  - Serve as scratch for the answer LLM during a live session.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class Utterance:
    text: str
    start_s: float
    end_s: float
    lang: str | None = None


class RollingWindow:
    """FIFO of utterances bounded by a time horizon.

    `horizon_s` is wall-clock against the latest utterance's `end_s`.
    """

    def __init__(self, horizon_s: float = 180.0):
        self.horizon_s = horizon_s
        self._q: deque[Utterance] = deque()

    def add(self, u: Utterance) -> None:
        self._q.append(u)
        self._trim()

    def _trim(self) -> None:
        if not self._q:
            return
        cutoff = self._q[-1].end_s - self.horizon_s
        while self._q and self._q[0].end_s < cutoff:
            self._q.popleft()

    def text(self) -> str:
        return " ".join(u.text for u in self._q)

    def utterances(self) -> list[Utterance]:
        return list(self._q)

    def __len__(self) -> int:
        return len(self._q)

    def clear(self) -> None:
        self._q.clear()
