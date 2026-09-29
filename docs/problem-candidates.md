# Problem Candidates (synthesis of tracks A-E, 2026-09-29)

Evidence base: track-A-failures.md (7 ranked failures), track-B-honcho.md (Honcho write/read paths + 5 Jev fixes),
track-C-landscape.md (6 OSS blocks, none does typed calibrated judgment), track-D-jevmap.md (6 FIT + 3 NOT),
track-E-gap.md (~28 Jev-memory repos, gap open: no Honcho-shaped full lifecycle).

Locked constraints:
1. Jev only judges (choice/score/noul), never generates prose, never does math/dates; code owns budgets, decay, packing.
2. Plain language docs, no em dash character anywhere, never fabricate (mark NOT VERIFIED).
3. Local-first SQLite, content-hash caching, per-user caps + kill switch if public.
4. Every gate tuned on labeled data, thresholds never ported across question types.
5. Bar: both judges score 1-10, each axis; >8 proceeds.

## Candidate 1: Full-lifecycle Jev memory SDK + server + one-command eval
Problem: agents drown in junk memory and bloated injection; every existing layer burns an LLM per read/write
(A: bloat, junk, LLM-everything cost; B: deriver zero-yield calls, uncapped injection, over-iteration;
C: no OSS layer does typed calibrated judgment). Nothing on GitHub covers all gates (E).
Fix: Honcho-compatible SDK where Jev gates admit (choice triage), importance (score), dedupe/contradiction (noul),
supersede (choice on code-ordered pairs), relevance rerank (topical noul, 0.58 gate + 45pct band, cap 8),
budget packing in code; thin MCP/server for non-Python; labeled eval harness in one command; live playground.
Why huge: direct contrast vs reference platform, every gate Jev-native, SDK gets adoption + eval gets trust + playground gets stars.

## Candidate 2: Universal Jev retrieval-rerank adapter
Problem: embeddings miss and lost-in-the-middle bury the right fact (A: 15-25pp middle drop); most pipelines skip reranking.
Fix: store-agnostic adapter (Mem0, Honcho, Chroma, SQLite in; ranked facts out) with published bench.
Why smaller: jev-recall already proved demo-plus-bench for standalone rerank; gap is only store-agnostic packaging.

## Candidate 3: Forgetting-as-a-service lease sidecar
Problem: stale facts pile up, old and corrected values both retrieve (A: contradiction/stale, LOCOMO 20-40pp gap).
Fix: MCP sidecar giving every fact a lease; new evidence ends leases via Jev supersede votes; human override + ledger.
Why smaller: invalidate validated leases at small scale; gap is only productionizing; single-slice, not a platform.
