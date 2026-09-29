# Track S3: Server, MCP, Honcho-compat, Rollout Design

Date: 2026-09-29. Scope: C1 only (full-lifecycle Jev memory SDK + thin server + MCP + eval + playground).
Sources: track-B-honcho.md (Honcho paths), track-D-jevmap.md (Jev fit map), track-E-gap.md (gap shape), judgeA-round1.response.txt (A1-A5 must-answer attacks).
Rules: Jev judges only (choice/score/noul). Code owns budgets, math, packing, thresholds, cache, caps, kill switch. Thresholds tuned per task, never ported. Plain language. No fabricated billing.

## 1. Design principles (answers to Judge A)

- A1 (threshold porting, s4): no universal 0.58 gate ships as a default. Every gate ships with a per-task threshold file plus a calibration wizard. Server refuses to start a gate whose threshold has no labeled tuning record, unless explicit `allow_untuned=true` is set and logged.
- A2 (stacked latency, s4): at most one Jev request per turn on the hot path (parallel questions inside it). Write-path gates run async off-response. Every Jev call has timeout, cap, content-hash cache, and kill switch. Code-side budget packer runs with zero model calls.
- A3 (poisoning, s5): memory text is data, never instructions. Provenance on every fact, quarantine for suspect writes, code-owned supersede rules, signed writes, human override path. Detail in section 7.
- A4 (eval contamination, s3): one-command eval enforces train/test split and contamination checks (hash overlap report). Tuning writes thresholds; testing reads them read-only.
- A5 (Honcho drift, s3): conformance suite pins read semantics (representation + card first, then 40/60 summary/messages, contextTokens budget). Any change that breaks the suite blocks release.

## 2. Thin server: endpoints

Base: `GET /healthz` returns `{ok, version, jev_mode, kill_switch}`.

Memory write path (async gates, response does not wait for Jev):

- `POST /v1/memories`
  Request: `{user_id, session_id, text, kind_hint?, timestamp?, provenance {source, actor, signature?}}`
  Response: `{id, status: "accepted" | "quarantined", triage_queued: true}`
  Behavior: persist row, enqueue triage (choice) + importance (score) off-response. Suspect provenance goes to quarantine table, not the live index. Code owns the decision to quarantine based on signature/allowlist, Jev never decides trust.
- `GET /v1/memories?user_id=&query=&limit=` (debug/admin list, not the recall path)
- `DELETE /v1/memories/{id}` soft delete only. Response `{id, status: "tombstoned", restorable: true}`. Hard purge is a separate admin op with auth.

Recall path (hot path, max one Jev request):

- `POST /v1/recall`
  Request: `{user_id, session_id?, query, budget_tokens?, top_k?, allow_untuned?}`
  Steps in code: (1) SQLite FTS + vector shortlist (cheap, no model), (2) one parallel Jev noul topical relevance request over shortlist (one question per candidate, wording "Is passage about query", data-framed), (3) code ranks, applies per-task tuned gate + band + cap, packs to budget.
  Response: `{items: [{id, text, score, provenance}], applied {gate, band, cap, threshold_id}, cache {hits, misses}, jev {calls: 0|1, ms}}`
  Timeout: Jev call aborts at 1500 ms and recall falls back to shortlist order with `fallback: true` flagged.

Inject path (Honcho-compat assembly, code only, zero model calls):

- `POST /v1/context`
  Request: `{user_id, session_id, query?, context_tokens?, peer_target?, peer_perspective?, scope?, search_top_k?, max_observations?}`
  Response: `{prompt_chunk, layers {representation[], card, summary?, messages[]}, tokens {used, budget}, provenance[]}`
  Assembly order is fixed (see section 4). Truncation order: messages drop first (oldest), then summary drops to null, representation/card never silently reordered.

Admin/ops:

- `GET /v1/thresholds` lists `{gate, threshold, tuned_on, dataset_hash, date}` per gate.
- `POST /v1/calibrate {gate}` runs the wizard on labeled data, writes a new threshold record. Never copies a threshold from another gate.
- `POST /v1/admin/kill-switch {jev_enabled: bool, reason}` global Jev bypass. When off, recall uses shortlist order and writes skip Jev gates (marked `unjudged`).
- `GET /v1/eval-report` returns last eval run (split hashes, per-gate scores, contamination check).

Auth: bearer token per deploy, plus `user_id` scoping on every row. Per-user caps: max writes/min, max recall/min, max Jev items per request (cap 8 default ceiling for rerank candidates per call batch, tunable per task). Over-cap returns 429 with `retry_after_ms` (see section 6).

## 3. MCP interface

One server, same handlers as REST. Tools:

- `memory_write {text, kind_hint?}` maps to POST /v1/memories with session provenance auto-attached.
- `memory_recall {query, budget_tokens?}` maps to POST /v1/recall.
- `memory_context {query?, context_tokens?}` maps to POST /v1/context, returns the packed chunk.
- `memory_delete {id}` soft delete. `memory_restore {id}` undo.
- `memory_calibrate {gate}` admin only, requires admin token.

Non-Python harnesses use MCP; Python harnesses use the SDK directly against SQLite with no server hop. Server never adds semantics the SDK lacks: same ranker, same packer, same threshold files.

## 4. Honcho-compat layer

### 4.1 Objects (card-like, SDK dataclasses)

- `Fact {id, user_id, text, importance, p_cal, created_at, supersedes?, valid_from, valid_to?, provenance, embedding?}`
- `Card {user_id, lines[], updated_at, source_fact_ids[]}` convenience summary only, never separate truth. Regenerated by the generative LLM path, checked by one Jev noul if enabled.
- `Representation {facts[], query_scores?}` working set per recall.
- `Summary {short?, long?, updated_at}` prose by LLM, Jev votes only on refresh timing (drift score), never writes prose.

### 4.2 Two-layer injection order (fixed, tested)

Layer 1 base = representation + card first. Layer 2 = summary + messages fills the rest. Budget rule mirrors Honcho: subtract representation + card tokens first to get adjusted budget, then up to 40 percent of adjusted budget for summary (long if it fits and is longer than short, else short if it fits, else null), remainder for recent messages. `context_tokens` param caps total; default set per deploy config, never null in production (uncapped only in local dev with a warning). Truncation never reorders layer 1 below layer 2.

### 4.3 Compat matrix

| Honcho behavior | Our match | Proof |
|---|---|---|
| Session context with summary + messages | `POST /v1/context` returns both | conformance test `ctx_shape` |
| Peer-targeted context adds representation + card | layer 1 present only when peer_target set | `ctx_peer_target` |
| Representation + card subtracted first | adjusted budget math in code, unit tested | `budget_first` |
| 40/60 summary/messages split | `_select_summary` port with same rule | `budget_40_60` |
| Card is convenience, not truth | card lines cite source_fact_ids; search finds same facts | `card_grounded` |
| contextTokens cap enforced | total tokens <= budget, truncation logged | `budget_cap` |
| Observe scoping (peer may read own perspective) | scope/peer checks return 403 on cross-read | `scope_auth` |
| Soft lifecycle (no silent hard delete) | tombstone + restore | `soft_delete` |

Conformance suite: `jev-memory/eval/conformance/` runs against fixtures, asserts ordering, budget math, and auth. Release gate: all green or no ship. NOT VERIFIED against live Honcho server billing or latency; compat is semantic, not performance parity.

## 5. Self-host recipe

Single binary path (default): `pip install jev-memory`, `jev-memory init`, `jev-memory serve`. Runs API + MCP on one process, SQLite + sqlite-vec file local, no Postgres, no Redis. Write gates run in-process background queue.

Compose path (team scale): api + worker + sqlite file volume. Postgres optional: set `MEMORY_DSN` to switch the store backend; schema identical, FTS via pg_trgm + pgvector. No Redis required; queue is a table, worker polls.

Env: `JEV_API_KEY`, `JEV_MODEL_ROUTE` (default pinned route, documented), `MEMORY_DB_PATH`, `MEMORY_DSN?`, per-user rate caps, `KILL_SWITCH` initial state, `ALLOW_UNTUNED=false` default.

## 6. Cost math per 1k turns + 429 policy

Cost model (code-computed, deploy-tunable constants):

- Hot path per turn: 1 Jev request carrying up to N parallel noul questions (N = shortlist size, ceiling 8 per batch, more candidates = more batches but still off the critical truncation path). Input per item approx 350-600 tokens (query + passage, filtered state). At approx INR 4 per 1M input tokens: per-item cost approx INR 0.0014-0.0024. Per-turn rerank of 8 items approx INR 0.011-0.019 before output tokens (noul outputs are tiny). 1k turns approx INR 11-19 in Jev rerank spend. Mark NOT VERIFIED against live billing; harness logs actual tokens per call so each deploy can replace these constants.
- Write path per accepted memory: triage choice + importance score batched off-response; dedupe/contradiction nouls only against blocked neighbors (hash prefilter), cached by content-hash pair. Amortized well under 1 extra request per write at steady state. Supersede votes run only on contradiction-flagged pairs.
- What we do NOT spend: no LLM extractor per write, no LLM rewrite per read, no dialectic tool loop. Summary prose uses the deploy's own LLM only at drift-triggered boundaries, not per turn.

Free-gateway 429 policy (observed multi-hour retry-after windows on free routes):

1. Read `retry_after` once from headers/body, persist `jev_backoff_until`.
2. Until expiry: do model-free work only (shortlist order, cache hits, code packer). Never poll the gateway.
3. Reads degrade with `fallback: true` flag; writes queue gates for later instead of dropping.
4. Single flight per user: no retry storms; jittered single retry after expiry.
5. Paid route failover only if operator configured a second key; otherwise stay degraded, never silently switch semantics.

## 7. Poisoning and safety design (A3)

- Provenance required: every write carries source/actor; unsigned external content (email/doc paste) defaults to quarantine.
- Quarantine: suspect facts are retrievable only with `include_quarantined=true` + admin token, never injected into prompts.
- Supersede rules in code: a newer fact replaces an older one only if (a) same-slot noul/choice vote passes tuned threshold AND (b) provenance authority allows (user overrides third-party, never reverse) AND (c) timestamps parsed in code confirm ordering. Jev never compares dates.
- Human override: flagged contradictions surface in `GET /v1/review-queue`; resolution writes a ledger entry with before/after ids.
- Eval includes a red-team fixture (injected "forget everything / limit changed" payloads) that must not flip protected facts.

## 8. Eval contamination design (A4)

`jev-memory eval --data labeled/` enforces: split manifest (train/test ids + content hashes), threshold tuning reads train only, testing reads frozen thresholds, overlap check fails the run if any test hash appears in train. Report includes dataset hashes, threshold ids, per-gate precision/recall, and the hash-overlap verdict. Publishing a score without the manifest is a documented misuse.

## 9. Phased rollout with go/no-go

Phase 0 SDK core (weeks 1-2): store, gates, ranker, code packer, threshold files, unit tests. Go: budget math tests green, zero model calls in packer, no em dash in docs lint. No-go: any gate without a labeled tuning set stays behind `allow_untuned` guard.
Phase 1 eval + calibration (week 3): fixtures, train/test split, wizard, red-team set. Go: per-gate thresholds tuned, contamination check green, red-team protected facts hold. No-go: copy of one threshold to another gate for any reason.
Phase 2 server + MCP (week 4): REST + MCP over the same handlers, auth, caps, kill switch, compose file. Go: conformance suite green, load test (100 concurrent recalls, p95 fallback correct), kill-switch drill passes. No-go: drift from section 4 order or missing per-user caps.
Phase 3 playground (week 5): replay real runs, show gates firing, token savings, provenance. Go: replay uses only shipped eval fixtures, cost panel shows measured tokens not estimates. No-go: any fabricated number on the demo page.
Phase 4 public: docs, migration guide from Honcho, benchmark post with manifests. Go: both judges re-run, all axes above bar, uncertain list shrunk or labeled.

## 10. Open unknowns (NOT VERIFIED)

- Live Jev latency distribution at p95 under parallel 8-question batches; tune timeout from measured data.
- Live INR/1k-turn billing vs section 6 estimate; replace with metered run before quoting.
- sqlite-vec recall quality vs pgvector at 100k+ facts; parity test due in Phase 2.
- Honcho live-server parity beyond semantic conformance (their LLM-backed dialectic intentionally out of scope).
