# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

- `src/uncluttered_memory/gate.py` - one batch of typed judge questions, code enforces drop / quarantine / store. Unseen input fails closed to quarantine, never an exception. RuleJudge is an offline heuristic keyed by text features; it is not Jev.
- `src/uncluttered_memory/store.py` - SQLite with content-hash dedupe, provenance per row, soft tombstones (never rewrites), a real quarantine table, and per-user scoping.
- `src/uncluttered_memory/supersede.py` - code-ordered candidate pairs, relation vote via the judge protocol (same / contradict / supersede / unrelated), destructive acts need two agreeing judges, losing facts get soft tombstones with provenance, named-human override for restore / retire.
- `src/uncluttered_memory/recall.py` - 0.58 gate, 45% band, cap 8, code packs.
- `src/uncluttered_memory/inject.py` - card-first packing, whole-card truncation, hard budget.
- `src/uncluttered_memory/calibrate.py` - per-task threshold registry fingerprinted to the task name, refuses mismatched files, UNCALIBRATED default, train-only tuning.
- `src/uncluttered_memory/jev_client.py` - judge protocol with a native Jev client.
- `eval/run.py` - one-command eval over the frozen 50/50 split: per-gate precision/recall/F1, latency p50/p95, cost-per-1k estimate. Exits nonzero if tuning artifacts touch the test split.

Run: `python3 -m pytest tests/` (39+ unit tests, offline; the live test runs only when
`HERMES_CUSTOM_OPENCODE_AI_API_KEY` is set).

## Judge wiring

The judge protocol is Jev-shaped: typed calls (noul / choice / score) that each
return a verdict plus a confidence 0..1. The offline stubs (RuleJudge,
FakeJudge, RuleRelationJudge) are for unit tests only and are never labeled as
Jev.

`JevJudgeClient` talks native Jev at `https://opencode.ai/zen/v1/systemone` with
one model, `jev-1.13-free`, set via `UNCLUTTER_JEV_MODEL` (default
`jev-1.13-free`). It sends the request shape from the Tracky direct-mode
pattern (id-keyed `questions`, `state`, `answers`), reimplemented here in
Python. The API key comes from `HERMES_CUSTOM_OPENCODE_AI_API_KEY`, the session
header is `hermes-go-static-7f3a9c2e`.

There is no fallback model anywhere in this project. On HTTP 429 the client
raises `RateLimited` (with retry-after when present) and callers halt with a
plain message telling the operator the free window is rate-limited. Pending
items land in the quarantine table (`Store.admit`), never voted by a stub,
never redirected to another model.

## Honesty

No benchmark numbers are claimed for the seed labels. The eval prints its own
measured numbers with the judge identity on every run, cost is marked
ESTIMATE / NOT VERIFIED, and contamination checks run before anything is
scored.