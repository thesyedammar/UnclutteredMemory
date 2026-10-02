# Jev Memory: Master Plan (FROZEN 2026-09-29)

Honest claim: a local-first agent memory SDK where cheap typed Jev judgments gate every write and rank every read,
with budgets and math owned by code, measured by a one-command labeled eval.

Scores: Judge A (deepseek-v4.1-flash) C1 [9,9,8,8] PROCEED. Judge B (glm-5.3-flash) C1 [9,8,8,8] PROCEED.
Both HOLD C2/C3 (slices, kept as future C1 modules). Full verdicts: prompts/judgeA-round1.response.txt,
prompts/judgeB-round1.response.txt. Research: research/track-A/B/C/D/E + S1/S2/S3.

## What gets built and WHERE

- `src/gate.py`: admit triage (choice) + importance (score), one batched call, UNCALIBRATED-by-default.
- `src/store.py`: SQLite + sqlite-vec, content-hash dedupe, provenance + trust tier per fact, soft tombstones.
- `src/supersede.py`: code-ordered pairs, Jev relation vote, paired-judge agreement for destructive acts, human override.
- `src/recall.py`: topical noul rerank, 0.58 gate + 45pct band + cap 8, per-task tuned, deterministic prefilter.
- `src/inject.py`: Honcho-order packing (representation + card first, 40/60 summary/messages), whole-card truncation.
- `src/calibrate.py`: per-task wizard, threshold registry fingerprinted to task, refuses mismatched files, train-only command.
- `src/server.py` + MCP tools: write/recall/context/admin, per-user caps, kill switch.
- `eval/`: 7 suites ~640 cases, per-gate precision/recall/F1/MRR + latency AND-gate + cost per 1k, 50/50 frozen split,
  red-team (6 payload families + 60 clean controls, false-persist bar 0.10), one command.
- `playground/`: 5 static pages (replay, gates board, poisoning theater, budget packer, Honcho compare). PARKED to phase 4.
- What Ammar sees: `jev-memory run` prints per-gate passes + eval table; playground replays gates firing with confidences.

## Attack ledger (attack to guard, status)

- Judge capture / poisoning via literal votes (s5/s4): provenance stamp + trust tiers + quarantine + paired agreement + code-owned supersede. Status: in design (S1/S2).
- Threshold porting across tasks (s4/s3): registry fingerprinted, refuse mismatched files, UNCALIBRATED default. Status: in design (S1).
- Latency stacking (s4/s3): fused one-batch write call, content-hash cache, caps, kill switch. Status: in design (S1/S3).
- Eval contamination/circularity (s3/s2): frozen 50/50 split, tuning on test is hard error, held-out families. Status: in design (S2).
- Honcho drift (s3): 8-row compat matrix + conformance suite gate. Status: in design (S3).
- Scope implosion (s3): sequence admit/dedupe/rerank + eval first, park playground. Status: accepted, phased below.
- Paraphrase contradiction catch (open Q1): UNKNOWN, first eval item. Benchmark will answer.
- Tuning cost at eval time (open Q2): UNKNOWN, measured in phase 1, reported before claims.

## Never-say list

Never claim: prevents poisoning, verifies facts, beats Honcho/Mem0 numbers, universal thresholds, solved memory.
Say instead: gates, scores, reduces, measured X on our labeled set (n=640, split frozen).

## Phased rollout with go/no-go

- P1 SDK gates + calibration + frozen eval: GO only if both judges hold PROCEED (done) and eval runs green on seed labels.
- P2 red-team + compat suite: GO only if false-persist <= 0.10 and conformance passes.
- P3 server/MCP + caps + kill switch: GO only if p95 recall latency within budget and 429 degrade proven.
- P4 playground + public repo polish: GO only if P1-P3 green without scope cuts.

## Cost (measured, not promised)

- Jev ~INR 4/M input, ~INR 0.002/item; S3 estimate ~INR 11-19 per 1k turns NOT VERIFIED until P1 measures.
- Judge spend so far: 1x32K + 1x16K verdict calls. Eval tuning budget capped per run, reported each run.

## R2 addition (both judges, FROZEN)

- J1 Poison Gauntlet BUILDS (A [9,8], B [9,8]): scripted adversary in the eval, 4 attack families as code mutators,
  `jev gauntlet --record`, HUD with gate verdicts + ledger lines. Headline demo of P2.
- J2 Paise Parity bench BUILDS (B [9,7]): public long-memory bench 3 ways with live paise meters + sha256 receipts,
  pre-registered claims, whatever the ratio turns out to be. Second demo of P2.
- PARKED phase 5: memory market + leaderboard (A J2, collusion risk), self-red-teaming reads (A J3, scope),
  zero-trust hash-chained receipts (B J3, overlaps J1).

## Open items + next step

- Next: Ammar creates the GitHub repo; P1 scaffold (src layout + eval seed + conformance skeleton) lands first.
- Residuals (max 5): paraphrase-catch rate / tuning cost / label sourcing / live latency / sqlite-vec parity.

## Addendum 2026-10-02: build drift (frozen content above untouched)

- Package layout shipped as `src/uncluttered_memory/*`, not flat `src/*.py`.
- sqlite-vec was never adopted: the store is stdlib sqlite3 only, no vector extension.
- Suite counts grew past the 640-case sketch (frozen golden plus synthetic bulk, floors pinned per suite in the eval).
- Auto-activation bridge (P5): every fresh `Store.put` screens free and committees flagged pairs; see README plus `src/uncluttered_memory/autospot.py`.
