"""Honcho-order packing: card-likes first, whole-card truncation, fixed budget."""
from __future__ import annotations


class Injector:
    def __init__(self, budget_chars: int = 4000):
        self.budget = budget_chars

    def pack(self, cards: list) -> str:
        """cards: [(text, score)]. Whole cards only, best first, hard budget."""
        ordered = sorted(cards, key=lambda c: -c[1])
        out, used = [], 0
        for text, _ in ordered:
            if used + len(text) + 1 > self.budget:
                break
            out.append(text)
            used += len(text) + 1
        return "\n".join(out)
