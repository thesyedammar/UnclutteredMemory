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

# Read path (Recall.select).
RECALL_GATE = 0.58
RECALL_BAND = 0.45
RECALL_CAP = 8

# Packing budgets.
INJECT_BUDGET_CHARS = 4000
RECALL_PACK_BUDGET_CHARS = 4000

# Offline relation judges: minimum shared content tokens before the
# strict judge accepts a marker as being about the same slot.
RELATION_SHARED_TOKENS_MIN = 1
