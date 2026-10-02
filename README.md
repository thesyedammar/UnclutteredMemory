# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

- `src/uncluttered_memory/gate.py` - one batch of typed judge questions, code enforces drop / quarantine / store. Unseen input fails closed to quarantine, never an exception. RuleJudge is an offline heuristic keyed by text features; it is not Jev.
- `src/uncluttered_memory/store.py` - SQLite with content-hash dedupe, provenance per row, soft tombstones (never rewrites), a real quarantine table, an unresolved-conflict table, and per-user scoping.
- `src/uncluttered_memory/supersede.py` - code-ordered candidate pairs, relation vote via the judge protocol (supersede / coexist / conflict_unresolved / unrelated). Only an agreed supersede soft-tombstones the old fact; an agreed clash marks both facts conflict_unresolved and keeps both live, never a tombstone. Named-human override for restore / retire.
- `src/uncluttered_memory/recall.py` - the read path: gate, band, and cap constants live in the module; code packs.
- `src/uncluttered_memory/inject.py` - card-first packing, whole-card truncation, hard budget.
- `src/uncluttered_memory/calibrate.py` - per-task threshold registry fingerprinted to the task name, refuses mismatched files, UNCALIBRATED default, train-only tuning.
- `src/uncluttered_memory/jev_client.py` - judge protocol with a native Jev client.
- `eval/run.py` - one-command eval over the frozen split: per-suite pass table, admit precision/recall/F1, latency, cost-per-1k estimate. Exits nonzero if tuning artifacts touch the test split; an unreadable artifact fails the scan closed.

Install and run:

    pip install -e .
    python3 -m pytest tests/
    unclutter run

The live Jev test runs only when `HERMES_CUSTOM_OPENCODE_AI_API_KEY` is
set; everything else is offline.

## Eval labels

The frozen cases are rule-generated templates and paraphrase variants
across the admit, importance, dedupe, contradict, supersede, and rerank
gates. Every case carries the provenance label `synthetic-rule`; no
case is presented as a human label and the runner refuses cases that do
not carry the label. The report prints the case-file hash, the
provenance, and its own measured numbers on every run.

## Judge wiring

The judge protocol is Jev-shaped: typed calls (noul / choice / score)
that each return a verdict plus a confidence value. The offline stubs
(RuleJudge, FakeJudge, RuleRelationJudge) are for unit tests and the
offline eval only and are never labeled as Jev.

`JevJudgeClient` talks native Jev at `https://opencode.ai/zen/v1/systemone`
with one model, `jev-1.13-free`, set via `UNCLUTTER_JEV_MODEL` (default
`jev-1.13-free`). It sends the request shape from the Tracky direct-mode
pattern (id-keyed `questions`, `state`, `answers`), reimplemented here in
Python. The API key comes from `HERMES_CUSTOM_OPENCODE_AI_API_KEY`, the
session header is `hermes-go-static-7f3a9c2e`.

There is no fallback model anywhere in this project. On HTTP 429 the
client raises `RateLimited` (with retry-after when present) and callers
halt with a plain message telling the operator the free window is
rate-limited. Pending items land in the quarantine table
(`Store.admit`), never voted by a stub, never redirected to another
model.

Response parsing is pinned by recorded native fixtures under
`tests/fixtures/` (replayed offline through the real parser; derived
failure variants are labeled as such in the fixtures README).

## Honesty

No benchmark numbers are claimed for these labels: they are
rule-generated (provenance `synthetic-rule`), not human labels, and
this README quotes none of the eval numbers. The eval prints its own
measured numbers with the judge identity on every run, cost is marked
ESTIMATE / NOT VERIFIED, and contamination checks run before anything
is scored (train/test disjointness by case hash and normalized text,
artifacts fail closed).
