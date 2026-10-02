# Label audit 2026-10-02 (two runs, see note on nondeterminism)
Date: 2026-10-02. Model: jev-1.13-free (only model, no fallback). Commit: 90173d0.
Method: scripts/label_audit.py, every golden importance case through live Jev.
Result: 10/24 agree = 41.7% (run 2; run 1 also 10/24 with per-case flips, e.g. g-importance-0012 live=2 then live=5, so live votes vary run to run).
Honest reading: golden labels are human judgments; the offline scorer reproduces them (proven in tests); live Jev is an independent rater that agrees less than half the time and is itself nondeterministic. Live calibration of importance is open future work, not claimed here.

label audit: 24 golden importance cases, model=jev-1.13-free (the only model in this project; no fallback exists)
live = jev-1.13-free vote; label = golden expect (1..5).
INFORMATION ONLY: the agreement rate below gates nothing.
g-importance-0001 live=5    label=5    agree
g-importance-0002 live=5    label=5    agree
g-importance-0003 live=5    label=5    agree
g-importance-0004 live=5    label=5    agree
g-importance-0005 live=5    label=5    agree
g-importance-0006 live=5    label=5    agree
g-importance-0007 live=3    label=4    differ
g-importance-0008 live=3    label=4    differ
g-importance-0009 live=3    label=4    differ
g-importance-0010 live=3    label=4    differ
g-importance-0011 live=3    label=4    differ
g-importance-0012 live=5    label=4    differ
g-importance-0013 live=2    label=4    differ
g-importance-0014 live=3    label=4    differ
g-importance-0015 live=3    label=4    differ
g-importance-0016 live=3    label=4    differ
g-importance-0017 live=1    label=1    agree
g-importance-0018 live=1    label=1    agree
g-importance-0019 live=1    label=1    agree
g-importance-0020 live=1    label=1    agree
g-importance-0021 live=1    label=2    differ
g-importance-0022 live=5    label=2    differ
g-importance-0023 live=1    label=2    differ
g-importance-0024 live=1    label=2    differ
live-vs-label agreement (INFORMATION ONLY, never a gate): 10/24 = 41.7%
