from __future__ import annotations

from sarathi.qdetect.rolling import RollingWindow, Utterance


def test_empty_window():
    w = RollingWindow()
    assert len(w) == 0
    assert w.text() == ""


def test_add_and_text():
    w = RollingWindow(horizon_s=180)
    w.add(Utterance(text="hello", start_s=0.0, end_s=1.0))
    w.add(Utterance(text="world", start_s=1.0, end_s=2.0))
    assert w.text() == "hello world"
    assert len(w) == 2


def test_horizon_evicts_old():
    w = RollingWindow(horizon_s=10.0)
    w.add(Utterance(text="old", start_s=0.0, end_s=1.0))
    w.add(Utterance(text="recent", start_s=20.0, end_s=21.0))
    # `old` ends at 1.0; cutoff = 21.0 - 10.0 = 11.0; 1.0 < 11.0 → evicted.
    assert "old" not in w.text()
    assert "recent" in w.text()


def test_horizon_keeps_within():
    w = RollingWindow(horizon_s=10.0)
    w.add(Utterance(text="a", start_s=0.0, end_s=1.0))
    w.add(Utterance(text="b", start_s=5.0, end_s=6.0))
    w.add(Utterance(text="c", start_s=10.0, end_s=11.0))
    # cutoff = 11.0 - 10.0 = 1.0; a ends at 1.0 (NOT < 1.0) → kept.
    assert "a" in w.text()
    assert "b" in w.text()
    assert "c" in w.text()
