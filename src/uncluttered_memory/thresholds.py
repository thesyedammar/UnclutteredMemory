"""One home for every decision-threshold default in the package.

Logic paths read their cutoffs from here; no other module hardcodes a
numeric decision boundary. Gate.decide and Recall.select take every
cutoff as a parameter whose default is the value below, so tests and
calibration can override any of them without editing logic. The
per-task registry can override admit.durable only; everything else is
code-owned.
"""

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

# Read path (Recall.select).
RECALL_GATE = 0.58
RECALL_BAND = 0.45
RECALL_CAP = 8

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
