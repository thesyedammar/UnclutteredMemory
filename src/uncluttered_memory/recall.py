"""Read path: score candidates, gate 0.58, 45% band, cap 8, code packs."""
from __future__ import annotations


GATE = 0.58
BAND = 0.45
CAP = 8


class Recall:
    def select(self, scored: list, gate: float = GATE) -> list:
        """scored: [(text, score)]. Returns at most CAP texts.
        gate is overridable: per-task calibration lowers it, and that is
        when the 45% band does its cutting (at the default 0.58 the gate
        dominates, which is intended)."""
        kept = [(t, s) for t, s in scored if s >= gate]
        if not kept:
            return []
        best = max(s for _, s in kept)
        floor = best * (1 - BAND)
        kept = [(t, s) for t, s in kept if s >= floor]
        kept.sort(key=lambda x: -x[1])
        return [t for t, _ in kept[:CAP]]

    def pack(self, texts: list, budget_chars: int = 4000) -> str:
        out, used = [], 0
        for t in texts:
            if used + len(t) + 1 > budget_chars:
                break
            out.append(t)
            used += len(t) + 1
        return "\n".join(out)
