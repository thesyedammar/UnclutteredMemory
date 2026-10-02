"""One home for every decision-threshold default in the package.

Logic paths read their cutoffs from here; no other module hardcodes a
numeric decision boundary. Gate.decide and Recall.select take every
cutoff as a parameter whose default is the value below, so tests and
calibration can override any of them without editing logic. The
per-task registry can override admit.durable only; everything else is
code-owned.
"""

# Gate.decide branch precedence, stated plainly. The checks run in
# this fixed order and the first match wins:
#   1. conf < MIN_CONF            -> QUARANTINE (abstention, fail closed)
#   2. play > PLAY_DROP           -> DROP
#   3. sensitive > SENSITIVE_DROP -> DROP
#   4. stop >= STOP_BLOCK         -> QUARANTINE
#   5. durable >= DURABLE_MIN and importance >= IMPORTANCE_MIN -> STORE
#   6. anything else              -> DROP (not-durable-or-trivial)
#
# Why this order, branch by branch:
# - Confidence first: a judge that cannot answer never reaches a
#   content branch; abstention always quarantines.
# - Play second: the play verdict is high-precision by construction
#   (word-boundary laugh tokens, whole-line identity claims), so its
#   drop is safe to apply first. Junk is disposed of by the junk rule
#   even when the line also trips durable or stop signals, and a drop
#   leaks nothing.
# - Sensitive third: privacy outranks review. A private-data line
#   must not be stored and must not sit in the quarantine queue
#   either, so it takes the one disposition that keeps nothing
#   (drop), which is why it outranks stop: quarantine would still
#   retain the text in its table.
# - Stop fourth: the binary block-or-pass call is the strongest deny
#   among the remaining branches. An over-held line waits in
#   quarantine for review while a wrongly admitted one is already
#   stored, so a block is never overridden by durable or importance;
#   deny wins every conflict with admit.
# - Durable last: STORE is the only admitting branch, so it runs
#   after every deny has had its chance. A line reaching it has
#   survived play, sensitive, and stop with no negative verdict.
#
# The reason strings in gate.py echo the effective cutoff of the
# branch that fired ("play>0.7", "sensitive>0.7", "stop>=0.58",
# "uncertain-low-conf", "durable+important", "not-durable-or-trivial"),
# so a multi-signal input records which rule owned the outcome.
# tests/test_gate_precedence.py pins the outcome and the reason string
# for every pair of branches firing at once, the headline multi-signal
# cases, and the boundary comparisons.

# Write gate (Store.admit -> Gate.decide).
MIN_CONF = 0.6  # judge confidence below this abstains -> QUARANTINE
PLAY_DROP = 0.7  # play above this -> DROP
SENSITIVE_DROP = 0.7  # sensitive above this -> DROP
STOP_BLOCK = 0.58  # stop at or above this -> QUARANTINE
DURABLE_MIN = 0.58  # durable at or above this can STORE
IMPORTANCE_MIN = 3  # importance at or above this can STORE

# Live-judge stop answer mapping (JevJudgeClient._judge_vote).
# The stop question is choice-bimodal with criteria s0 block / s1
# allow: s1 maps to a stop signal of 0.0 (pass) and anything else maps
# to 1.0 (block), which quarantines at STOP_BLOCK. Anything else covers
# s0, a missing stop answer, and an unreadable choice: a judge that
# fails to pick allow is read as block, fail closed. Rationale: block
# is the safe default (an over-held memory waits in quarantine for
# review, while a wrongly admitted one is already stored), and the
# bimodal map keeps the safety call one crisp bit instead of a graded
# score whose middle voltages could smuggle a block past the cutoff.
STOP_ALLOW_CHOICE = "s1"
#: Block-side key of the stop choice pair. _judge_vote builds the stop
#: question criteria as {STOP_BLOCK_CHOICE: block, STOP_ALLOW_CHOICE:
#: allow} and _stop_agreement_cap reads the answer probabilities under
#: the same two keys, so the margin is |p(allow) - p(block)|. The two
#: constants are coupled: renaming one key without the other silently
#: moves the margin (the missing key reads as 0.0), which is why both
#: live here and a test pins the criteria keys and the cap together.
STOP_BLOCK_CHOICE = "s0"
# When the judge is split on the stop question its vote carries little
# signal, so confidence is capped near chance: conf is at most
# STOP_AGREE_CAP plus the |p(allow) - p(block)| margin read from the
# stop answer probabilities. A near-tie caps conf near 0.5, below
# MIN_CONF, so Gate.decide quarantines on low confidence even when the
# raw values would STORE. A comfortable margin leaves the
# durable-derived confidence untouched. Missing probabilities (older or
# stub answer shapes) mean no cap. Only the stop question feeds this
# cap: spread across the five importance levels is normal granularity,
# while a split on the binary safety call means the safety call itself
# is uncertain.
STOP_AGREE_CAP = 0.5

# Live-judge confidence from durability (JevJudgeClient._judge_vote).
#
# conf = CONF_BASE - abs(durable - CONF_MIDPOINT) * CONF_SLOPE, so a
# maximally uncertain durable verdict (0.5) carries CONF_BASE and a
# fully decided one (0.0 or 1.0) carries CONF_BASE - 0.5 * CONF_SLOPE
# = 0.875. The slope is deliberately shallow: durability uncertainty
# barely moves confidence, because real abstention comes from the
# stop-agreement cap falling below MIN_CONF, not from this curve.
CONF_BASE = 0.9
CONF_MIDPOINT = 0.5
CONF_SLOPE = 0.05


def durable_confidence(durable: float) -> float:
    """Confidence for a durable verdict: base minus slope times distance."""
    return CONF_BASE - abs(durable - CONF_MIDPOINT) * CONF_SLOPE

# Read path (Recall.select).
RECALL_GATE = 0.58
RECALL_BAND = 0.45
RECALL_CAP = 8

# Near-duplicate dedupe (Store.put second stage).
#
# Exact normalized-hash match dedupes first (unchanged). When the hash
# misses, put compares the token set of the new text against live rows
# in the same user scope and merges at or above DEDUP_JACCARD.
#
# Threshold choice, stated plainly: tokens are whitespace splits of the
# normalized text, case- and punctuation-sensitive, matching the
# existing contract that case and punctuation are content (a test pins
# that "Ship the build" and "ship the build." are distinct rows). On
# that tokenization every frozen DISTINCT dedupe label scores at or
# below 0.80, with the nearest miss g-dedupe-0013 ("fold the winter
# coats today" vs "fold the winter coats", 4/5 = 0.80). DEDUP_JACCARD
# sits one step above at 0.85, so the whole frozen set passes with
# margin and no label moves.
#
# What 0.85 catches and what it does not: token reorderings always
# score 1.0 and merge; a dropped or added word merges once the fact
# is long enough (7 tokens: 6/7 = 0.857). A single-word change in a
# short fact stays DISTINCT (4 tokens with one swap: 3/5 = 0.60), and
# heavily reworded paraphrases with little token overlap stay
# DISTINCT too. That limit is honest: this stage catches
# near-duplicates, not deep semantic equivalence.
DEDUP_JACCARD = 0.85

# Auto-spot suspicion screen (Store.put fresh-insert bridge, autospot.py).
#
# After every fresh insert, put scores the new text by token-set
# Jaccard against live rows in the same user scope and flags pairs
# at or above AUTOSPOT_MIN_JACCARD that also carry a change signal
# (an update/negation marker in the new text, or a differing
# content detail). Flagged pairs go to the existing committee
# (offline Strict+Lenient pair, live dual-Jev path where wired);
# the committee verdict applies, never the screen.
#
# Threshold choice, stated plainly with measured anchors: dedupe
# merges at DEDUP_JACCARD above, so the screen must sit well below
# it to catch reworded same-slot updates. On the frozen relation
# fixtures the weakest genuine same-slot update scores 0.40
# ("the office is at 1 Main St" vs "the office moved to 2 Main
# St": 4 shared tokens over a 10-token union), while a clearly
# disjoint pair scores 0.33 ("the kettle is blue" vs "the toaster
# is silver"). AUTOSPOT_MIN_JACCARD sits below the weakest genuine
# update with margin, so the screen favors recall: a disjoint pair
# that passes is vetoed to KEEP by the committee (free offline,
# capped live), while a missed clash would live on as a silent
# contradiction. The screen never merges or tombstones; it only
# nominates, and deep paraphrases with little token overlap stay
# below it by construction (same documented limit as dedupe).
AUTOSPOT_MIN_JACCARD = 0.30

# Auto-spot committee cap (autospot.run_after_put).
#
# At most this many flagged pairs reach the committee per fresh
# insert, strongest suspicion score first. Bounds the per-write
# committee cost: the live path asks two differently worded Jev
# questions per pair, so the worst case is twice this many live
# calls per write, well inside the per-minute server rate budget.
# Offline votes cost no budget and no network.
AUTOSPOT_MAX_PAIRS_PER_WRITE = 5

# RuleJudge vote levels: heuristic stub outputs, not decision cutoffs.
# The cutoffs that read these live above. Centralized here so the
# threshold-pin test covers every numeric literal the judge path
# emits; gate.py reads them as th.* and holds no numeric vote literal
# of its own.
FILLER_LEVELS = (0.05, 1, 0.1)
FILLER_CONF = 0.9
PLAY_LEVELS = (0.3, 1, 0.2)
PLAY_SIGNAL = 0.85
PLAY_CONF = 0.8
SENSITIVE_LEVELS = (0.6, 2, 0.1)
SENSITIVE_SIGNAL = 0.9
SENSITIVE_CONF = 0.8
DURABLE_DURABLE = 0.9
DURABLE_STOP = 0.05
DURABLE_CONF = 0.8
DURABLE_HARD_IMPORTANCE = 5
DURABLE_SOFT_IMPORTANCE = 4
UNCERTAIN_LEVELS = (0.5, 2, 0.4)
UNCERTAIN_CONF = 0.2

# Fail-closed protocol defaults: the vote JudgeClient and FakeJudge
# emit for unseen or unmapped input. Low confidence by construction,
# so Gate.decide quarantines it under MIN_CONF.
FAIL_CLOSED_LEVELS = (0.5, 2, 0.5)
FAIL_CLOSED_CONF = 0.0

# Packing budgets.
#
# Chars-as-proxy decision, stated plainly: INJECT_BUDGET_CHARS and
# RECALL_PACK_BUDGET_CHARS are character counts, used as a cheap
# proxy for model token budgets. The working rule is about 4 chars
# per token for English prose, so 4000 chars is roughly 1000
# tokens. Chars are chosen because they are exact, dependency free,
# and stable across judges, while real tokenizers differ per model
# and would tie packing to one tokenizer.
#
# Where the proxy can mis-split: it undercounts dense scripts
# (CJK text carries near one token per char), overcounts
# whitespace-heavy or repeated-char text, and cannot see real
# token split points, so a budget cut can land mid-word or mid
# token. Packing therefore cuts only on whole-card boundaries
# (Injector.pack and Recall.pack never emit a partial card) rather
# than slicing text at the char limit; the boundary error is at
# most one card, never a half card.
INJECT_BUDGET_CHARS = 4000
RECALL_PACK_BUDGET_CHARS = 4000

# Offline relation judges: minimum shared content tokens before the
# strict judge accepts a marker as being about the same slot. Content
# excludes stopwords and numbers (digits and spelled-out numerals), so
# one shared token or a shared number is never a slot: near-homonym
# subjects and address/number near-misses read as unrelated and the
# pair vetoes the destructive act.
RELATION_SHARED_TOKENS_MIN = 2

# Server rate caps (MemoryServer, per rolling minute window).
#
# Two budgets, both enforced per server instance: at most
# RATE_LIMIT_CALLS_PER_MIN requests and at most
# RATE_LIMIT_CHARS_PER_MIN request-body chars per rolling 60 seconds.
# Chars are the same cheap token proxy as the packing budgets (about
# 4 chars per token), so 200000 chars is roughly 50000 tokens per
# minute. A request over either budget is refused with a 429-style
# refusal and one structured log line; nothing is stored, recalled,
# or quarantined by the refused call. Both are constructor
# parameters on RateLimiter, so tests set tiny budgets without
# touching this file.
RATE_LIMIT_CALLS_PER_MIN = 120
RATE_LIMIT_CHARS_PER_MIN = 200000
RATE_LIMIT_WINDOW_SECS = 60

# Per-user memory cap (live facts per user scope).
#
# The master plan calls for per-user caps on the write path. The cap
# counts live (non-tombstoned) facts rows in one user scope. A fresh
# insert that would grow a full scope past the cap is refused: a
# direct put() raises MemoryCapExceeded (nothing is stored live), and
# admit() holds the item in quarantine with reason
# "per-user-memory-cap" instead of storing it, so the item waits for
# human review instead of vanishing. Near-duplicate merges and
# exact-text hits add no row and never trip the cap; each user scope
# is counted separately. Store takes the cap as a constructor
# parameter defaulting to this value (None means unbounded), so tests
# set tiny caps without touching this file.
PER_USER_MEMORY_CAP = 10000

# Quarantine reason recorded when an admit is held for review only
# because the user scope is at its memory cap.
MEMORY_CAP_QUARANTINE_REASON = "per-user-memory-cap"
