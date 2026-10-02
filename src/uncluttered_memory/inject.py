"""Honcho-order packing: card-likes first, whole-card truncation, fixed budget."""
from __future__ import annotations

from . import thresholds as th


class Injector:
    def __init__(self, budget_chars: int = th.INJECT_BUDGET_CHARS):
        self.budget = budget_chars

    def pack(self, cards: list) -> str:
        """cards: [(text, score)]. Whole cards only, best first, hard budget.

        Exact-duplicate card texts pack once: cards arrive best
        first, so the first occurrence wins and later copies are
        skipped without spending budget. Distinct cards are never
        merged here; near-duplicate merging is the store write
        path, not the inject read path.
        """
        ordered = sorted(cards, key=lambda c: -c[1])
        out, used, seen = [], 0, set()
        for text, _ in ordered:
            if text in seen:
                continue
            seen.add(text)
            if used + len(text) + 1 > self.budget:
                break
            out.append(text)
            used += len(text) + 1
        return "\n".join(out)
