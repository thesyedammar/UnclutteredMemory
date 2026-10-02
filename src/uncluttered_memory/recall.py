"""Read path: score candidates, gate, band, cap; code packs.

Every cutoff (gate, band, cap, pack budget) is a parameter whose
default lives in thresholds.py; nothing numeric is hardcoded here.
"""
from __future__ import annotations

from . import thresholds as th

GATE = th.RECALL_GATE
BAND = th.RECALL_BAND
CAP = th.RECALL_CAP


class Recall:
    def select(self, scored: list, gate: float = th.RECALL_GATE,
               band: float = th.RECALL_BAND,
               cap: int = th.RECALL_CAP) -> list:
        """scored: [(text, score)]. Returns at most cap texts.

        gate is overridable: per-task calibration lowers it, and that is
        when the band does its cutting (at the default gate the gate
        dominates, which is intended)."""
        kept = [(t, s) for t, s in scored if s >= gate]
        if not kept:
            return []
        best = max(s for _, s in kept)
        floor = best * (1 - band)
        kept = [(t, s) for t, s in kept if s >= floor]
        kept.sort(key=lambda x: -x[1])
        return [t for t, _ in kept[:cap]]

    def pack(self, texts: list,
             budget_chars: int = th.RECALL_PACK_BUDGET_CHARS) -> str:
        out, used = [], 0
        for t in texts:
            if used + len(t) + 1 > budget_chars:
                break
            out.append(t)
            used += len(t) + 1
        return "\n".join(out)
