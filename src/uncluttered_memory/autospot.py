"""Auto-activation bridge: free suspicion screen plus committee verdict.

Store.put calls run_after_put after every fresh insert. The screen
is free (token overlap plus change markers or a differing detail,
no judge call); flagged pairs go to the existing committee and the
committee verdict applies:

- offline: the heterogeneous Strict+Lenient pair via
  offline_relation_pair (no network, fixture votes in tests).
- live: the dual-Jev path via live_confirmed_decide where the
  operator wired a live pair, which needs live agreement plus
  offline agreement for any destructive act.

Verdict application with provenance: an agreed supersede
tombstones the old fact, an agreed clash marks both facts
conflict_unresolved and records the pair; both write reason
"<relation>-auto-spot" with actor "auto-spot", so auto rows read
apart from manual committee rows (actor "code") and human rows.
KEEP and every veto write nothing.

Failure modes, argued as accepted risk: the offline-only default
lets two heuristics tombstone a live fact during an ordinary put
with no human and no live rater. That is the same evidence bar as
the manual committee path, not a weaker one: the pair is
heterogeneous by construction (Strict plus Lenient genuinely
disagree on crafted near-misses, pinned by tests), any
disagreement vetoes to KEEP, and a tombstone is soft (the row and
its reason survive; restore and put-resurrection clear it through
the tested shared path). The blast radius of a wrong-but-agreed
verdict is one restorable row with auto-spot provenance pointing
at the cause, versus the alternative of silent contradictions
living on unflagged. Operators who want a human in the loop pass
auto_spot=False and run the committee manually.

Caps: at most max_pairs flagged pairs reach the committee per
write (strongest suspicion first); the live path additionally
checks the server rate limiter before each pair and stops with
rate_limited=True when the budget is spent. A halted judge
(RateLimited, transport failure, malformed answer) never
fabricates a vote: the pair keeps both facts live, the run stops
at the first halt instead of hitting a demonstrably failed judge
again for the remaining pairs, and the run reports halted=True.

The screen reuses the exact committee signals (the jev_client
marker patterns and content-token slot definition) so the
nominator and the committee cannot drift apart.
"""
from __future__ import annotations

from . import thresholds as th
from .jev_client import (JevError, RateLimited, _NEGATION_RE,
                         _NUMBER_WORDS, _STRONG_UPDATE_RE, _TOKEN_RE,
                         _WEAK_UPDATE_RE, _content_tokens,
                         live_confirmed_decide, offline_relation_pair)
from .store import normalize, token_jaccard
from . import supersede as supmod

#: Actor recorded on auto-applied tombstones and conflict rows.
AUTOSPOT_ACTOR = "auto-spot"

#: Reason suffix on auto-applied rows: "<relation>-auto-spot".
AUTOSPOT_REASON_SUFFIX = "-auto-spot"


def has_change_signal(new_text: str) -> bool:
    """An update or negation marker in the new text.

    Reuses the committee marker patterns, so a wording the
    committee reads as an update or a clash reads the same here.
    """
    lowered = new_text.lower()
    return bool(_STRONG_UPDATE_RE.search(lowered)
                or _WEAK_UPDATE_RE.search(lowered)
                or _NEGATION_RE.search(lowered))


def detail_differs(old_text: str, new_text: str) -> bool:
    """The slot-bearing content tokens differ between the texts.

    Content excludes stopwords and numbers (the committee slot
    definition), so a pure rewording with identical content reads
    as no differing detail; a changed number alone does not count
    here, it counts in number_detail_differs below.
    """
    return _content_tokens(old_text) != _content_tokens(new_text)


def number_detail_tokens(text: str) -> set:
    """Digit-bearing and spelled-out number tokens in a text.

    Any alphanumeric token containing a digit counts ("4pm" and
    "5pm" differ as details, as do "12" and "44"), plus the
    spelled-out numerals the committee treats as numbers. Reuses
    the committee tokenizer and number-word set so the screen and
    the committee read the same tokens.
    """
    return {t for t in _TOKEN_RE.findall(text.lower())
            if t in _NUMBER_WORDS or any(ch.isdigit() for ch in t)}


def number_detail_differs(old_text: str, new_text: str) -> bool:
    """A number detail changed between the texts.

    The canonical update shape the first judge round caught this
    screen missing: "demo at 4pm" revised to "demo at 5pm" shares
    every content token and carries no update marker, so neither
    the marker check nor the content check fires, yet the slot
    value moved. Flagging nominates only: the committee still
    decides, and a marker-free number swap the offline pair reads
    as unrelated vetoes to KEEP with both facts live.
    """
    return number_detail_tokens(old_text) != number_detail_tokens(new_text)


def suspicion_score(old_text: str, new_text: str) -> float:
    """Free overlap score in [0.0, 1.0]: token-set Jaccard."""
    return token_jaccard(old_text, new_text)


def is_suspicious(old_text: str, new_text: str,
                  min_jaccard: float = th.AUTOSPOT_MIN_JACCARD) -> bool:
    """Free screen: overlap plus a change signal or a differing detail.

    Exact normalized duplicates never flag (dedupe owns them, never
    a clash). Below min_jaccard the pair is unrelated wording and
    the committee never sees it. Above it, the pair still needs a
    reason to suspect a clash: a change marker in the new text, a
    differing content detail, or a changed number detail (times,
    counts, and versions move slots without any marker wording).
    The screen nominates only; the committee decides.
    """
    if normalize(old_text) == normalize(new_text):
        return False
    if token_jaccard(old_text, new_text) < min_jaccard:
        return False
    return (has_change_signal(new_text)
            or detail_differs(old_text, new_text)
            or number_detail_differs(old_text, new_text))


def find_candidates(store, new_id: int, new_text: str, user: str,
                    min_jaccard: float = th.AUTOSPOT_MIN_JACCARD,
                    max_pairs: int = th.AUTOSPOT_MAX_PAIRS_PER_WRITE) -> tuple:
    """Suspicious live pairs for a fresh row, strongest first.

    Scans live rows in the same user scope only (cross-user rows
    never flag: the dedupe key and live reads are scoped the same
    way). Returns (candidates, dropped), where candidates holds at
    most max_pairs (old_id, old_text, score) entries ordered by
    score descending (lowest id wins ties), and dropped counts the
    flagged pairs cut by the cap.
    """
    scored = []
    for fid, text, *_rest in store.live(user=user):
        if fid == new_id:
            continue
        if not is_suspicious(text, new_text, min_jaccard=min_jaccard):
            continue
        scored.append((fid, text, suspicion_score(text, new_text)))
    scored.sort(key=lambda c: (-c[2], c[0]))
    kept = scored[:max_pairs]
    return kept, len(scored) - len(kept)


def _resolve_offline(relation_pair):
    """The committee offline pair: override or the shipped pair."""
    return relation_pair if relation_pair is not None else offline_relation_pair()


def run_after_put(store, new_id: int, new_text: str, user: str,
                  min_jaccard: float = th.AUTOSPOT_MIN_JACCARD,
                  max_pairs: int = th.AUTOSPOT_MAX_PAIRS_PER_WRITE,
                  relation_pair=None, live_pair=None,
                  rate_limiter=None,
                  actor: str = AUTOSPOT_ACTOR,
                  reason_suffix: str = AUTOSPOT_REASON_SUFFIX) -> dict:
    """Bridge entry: screen a fresh insert, committee the flagged pairs.

    relation_pair overrides the offline committee (tests pass
    FakeRelationJudge fixture votes here; production uses the
    shipped Strict+Lenient pair). live_pair selects the live
    dual-Jev path (live_confirmed_decide over this live pair plus
    the offline pair); None means offline committee only and no
    network is touched. rate_limiter gates live votes only
    (offline votes cost no budget): before each live pair the
    limiter is charged len(old)+len(new) chars, and an exhausted
    budget stops the run with rate_limited=True, leaving the
    remaining pairs unvoted and live.

    Returns a plain summary: flagged, dropped_by_cap, checked,
    tombstoned, conflicts, kept, halted, rate_limited, outcomes.
    Every outcome names old_id, new_id, relation, action, applied,
    and the reason each applied row carries. Pairs never voted
    (rate budget spent, or a judge halt stopped the run) are
    itemized too with action KEEP and applied False, so outcomes
    always account for every flagged pair: no skipped pair is
    inferable only by arithmetic.
    """
    candidates, dropped = find_candidates(store, new_id, new_text, user,
                                          min_jaccard=min_jaccard,
                                          max_pairs=max_pairs)
    summary = {"flagged": len(candidates) + dropped,
               "dropped_by_cap": dropped, "checked": 0,
               "tombstoned": [], "conflicts": [], "kept": [],
               "halted": False, "rate_limited": False, "outcomes": []}
    if not candidates:
        return summary
    off_a, off_b = _resolve_offline(relation_pair)
    pairs = list(candidates)
    for idx, (old_id, old_text, _score) in enumerate(pairs):
        if live_pair is not None:
            if rate_limiter is not None:
                ok, _retry = rate_limiter.check(len(old_text)
                                               + len(new_text))
                if not ok:
                    summary["rate_limited"] = True
                    for rest_id, _t, _s in pairs[idx:]:
                        summary["kept"].append(rest_id)
                        summary["outcomes"].append(
                            {"old_id": rest_id, "new_id": new_id,
                             "relation": "unrelated", "action": "KEEP",
                             "applied": False,
                             "reason": "rate-budget-exhausted"})
                    break
            try:
                dec = live_confirmed_decide(old_text, new_text,
                                            live_pair[0], live_pair[1],
                                            off_a, off_b)
            except RateLimited:
                summary["halted"] = True
                summary["kept"].append(old_id)
                summary["outcomes"].append(
                    {"old_id": old_id, "new_id": new_id,
                     "relation": "unrelated", "action": "KEEP",
                     "applied": False, "reason": "judge-rate-limited"})
                for rest_id, _t, _s in pairs[idx + 1:]:
                    summary["kept"].append(rest_id)
                    summary["outcomes"].append(
                        {"old_id": rest_id, "new_id": new_id,
                         "relation": "unrelated", "action": "KEEP",
                         "applied": False,
                         "reason": "judge-halted-skipped"})
                break
            except JevError:
                summary["halted"] = True
                summary["kept"].append(old_id)
                summary["outcomes"].append(
                    {"old_id": old_id, "new_id": new_id,
                     "relation": "unrelated", "action": "KEEP",
                     "applied": False, "reason": "judge-halted"})
                for rest_id, _t, _s in pairs[idx + 1:]:
                    summary["kept"].append(rest_id)
                    summary["outcomes"].append(
                        {"old_id": rest_id, "new_id": new_id,
                         "relation": "unrelated", "action": "KEEP",
                         "applied": False,
                         "reason": "judge-halted-skipped"})
                break
        else:
            dec = supmod.decide(old_text, new_text, off_a, off_b)
        summary["checked"] += 1
        reason = dec.relation + reason_suffix
        if dec.agreed and dec.action == "TOMBSTONE":
            store.tombstone(old_id, new_id, reason, actor)
            summary["tombstoned"].append(old_id)
            applied = True
        elif dec.agreed and dec.action == "CONFLICT":
            store.mark_conflict(old_id, new_id, reason, actor)
            summary["conflicts"].append(old_id)
            applied = True
        else:
            summary["kept"].append(old_id)
            applied = False
            reason = "veto-keep"
        summary["outcomes"].append(
            {"old_id": old_id, "new_id": new_id,
             "relation": dec.relation, "action": dec.action,
             "applied": applied, "reason": reason})
    return summary
