# Track E: GitHub gap scan - Jev memory layer

Date: 2026-09-29. Sources: GitHub repo search (`jev memory`, `typesafe memory`,
`system-one agent memory`) plus awesomejev.com directory snapshot (691 entries,
refreshed 2026-09-20, full page cached 2026-09-29). Star counts fetched live
from api.github.com on 2026-09-29 unless noted; treat as approx.

Reference: Honcho (github.com/plastic-labs/honcho, open source) is the shape to
beat: dialectic reasoning, card/representation/summary objects, two-layer
context injection, contextTokens budget. Honcho star count NOT VERIFIED
(API quota exhausted before fetching; re-check before quoting).

## What exists: Jev + memory repos

| Repo | Stars (approx, 2026-09-29) | Lang | What it does |
| --- | --- | --- | --- |
| kitfunso/hippo-memory | 763 | TypeScript | Agent memory that learns what is wrong (mark-a-memory-wrong, newer facts replace old). Local SQLite + MCP server, multi-harness init. Jev is OPT-IN hosted reranker only, not core. Biggest star count but barely a Jev project. |
| libingzheren/Jev-Mem | 118 | Python | System-One Controlled Agentic Memory. Largest pure-Jev memory repo. Library shape. |
| Avinash-jetwani/jevmem | 93 | TypeScript | Automatic project memory for Claude Code (also Cursor, Codex). npm package, CLI + MCP server + hooks, audit, label-driven refit, bench/eval dirs. Most complete product shape, but coding-project scoped. |
| AustinAWay/Working-Memory-Jev | 77 | Python | FALSE POSITIVE: cognitive-psychology teaching aid (working-memory load in instructional text), not agent memory. Ignore for gap math. |
| nylon-memory/NylonME | 45 | Rust | Memory engine: memory as woven graph of threads (facts/emotions/timing/relationships/beliefs) with weighted edges. Jev optional for accuracy. |
| samdotmak/jev-recall | 38 | TypeScript | Retrieval-only rerank library: one calibrated yes/no per memory in a single Jev request. Bench (238 memories, 18 labeled requests) + live demo site. LLM-reranker quality at semantic-search price. |
| chopratejas/invalidate | 22 | Python | Invalidation-only layer: every fact gets a lease, new evidence ends it via Jev votes. Evals + adapters. Explicitly NOT a store, no embeddings, no server. |
| CheshiAI/Cheshi | 19 | C | macOS workspace for Codex with Jev-powered conversation memory (find past sessions, revisit decisions with sources). App, not a reusable layer. |
| NicolasMontone/jev-memory | 14 | TypeScript | Long-term memory layer (write/retrieve/evict) for the Vercel AI SDK only. Single-harness SDK. |
| romiluz13/jevmory | 11 | Python | Coding-agent memory: every fact a verbatim quote graded by Jev confidence. Local-first SQLite, zero deps. Small, no eval visible. |
| poiuyjie/jev_project_context | 9 | Python | Evidence-first long-term experiment memory skill for coding agents, Jev layers optional. Skill shape. |
| Waxmell114514/jev-compaction | 4 | Python | Context compactor that can only score, never write (no fabricated facts). Offline demo. Compaction slice only. |
| Cairn-ink/cairn-jev-lab | 4 | JavaScript | Memory ADMISSION evaluator: editable cases, inspectable results. Eval/lab shape, not a runtime layer. |
| fellowship-dev/jev-second-brain | 3 | Python | Local-first Markdown memory alignment + source-linked search, Jev judgments optional. |
| KonghaYao/fast-memory | 2 | TypeScript | Agent memory built with Jev + LLM. Tiny, last push 2026-09-21. |
| ReallyArtificial/jev-by-example | 2 | JavaScript | Ten runnable Jev examples incl. memory conflicts, context selection, handoffs. Docs/shape reference, not a layer. |
| Sauhard74/mem-jev | 2 | Go | Deterministic procedural memory for agents. Tiny. |
| rohanarun/dynamic-context-engine | 1 | Python | Paragraph-level context with Jev for Codex/Claude/Hermes. SQLite + skills. Tiny. |
| willfish/pi-observational-memory-jev | 1 | TypeScript | Pi agent: Jev decides what to keep, compaction never rewrites transcript. Single-harness plugin. |
| arshiaez/system-one-memory | 1 | PowerShell | Token-efficient memory for Claude Code and Codex, Jev decides + LLM validates. Tiny. |
| Towzai/dsh-memory-jev | 0 | JavaScript | Memory plugin for DeepSeek Harness, typed Jev judgments on read/write. Single-harness plugin. |
| Pizzawookiee/jev-tree-memory | 0 | Python | Jev + n-ary memory tree for routing/retrieval. Sketch-size. |
| jrmcauliffe00/jev-memory | 0 | TypeScript | Jev-gated memory writes for the Strands harness. Single-harness slice. |
| leonininder/remember-me | 0 | Python | Decides what to hydrate: local topology recall + Jev gates. Tiny. |
| kerpopule/hermes-jev-skills | NOT VERIFIED | Python | Jev routing/memory/compaction/skill-selection for Hermes/Claude/Codex. Skills bundle. |
| litshing/hermes-jev-plugins | NOT VERIFIED | Python | Two Hermes plugins: prune context + gate permanent memory with Jev, fail-open. |
| ccdepsilon/jev-browser-memory-assistant | NOT VERIFIED | NOT VERIFIED | Browser memory: local BM25 + E5 recall, Jev semantic rerank. Chinese-language repo. |
| Mukul-svg/laya-swe | NOT VERIFIED | NOT VERIFIED | System-One decision models for coding-agent memory. Found via search, not star-checked. |

Compaction-adjacent (context layer, not long-term memory, for calibration):
awesomejev.com lists tamaratran/fast-jev-compaction at 4,548 stars (2026-09-20
snapshot), omp-jev-compaction, pi-fast-jev-compaction, pi-jev-context. These
prove the star appetite for Jev-gated context work and set the bar to beat.

## Verdict: is a Jev memory layer already done?

No. What exists are SLICES, each covering one gate or one harness:

- Retrieval-only: jev-recall (rerank at read, no write/evict lifecycle).
- Invalidation-only: invalidate (leases and supersede votes, explicitly not a store).
- Admission-eval-only: cairn-jev-lab (test what to remember, no runtime).
- Single-harness SDKs/plugins: NicolasMontone (Vercel), jrmcauliffe00 (Strands),
  Towzai (DeepSeek harness), willfish (Pi), litshing (Hermes). None portable.
- Project-scoped products: Avinash-jetwani/jevmem (most complete: CLI + MCP +
  audit + refit, but tied to coding-project memory for Claude/Cursor/Codex),
  Jev-Mem (library, no server, no budget enforcement, no eval harness visible).
- Jev-optional stores: hippo-memory (763 stars, Jev is an opt-in reranker),
  NylonME, jevmory, second-brain. Jev is a garnish, not the control plane.

Nobody ships the Honcho-shaped whole: write/retrieve/evict/inject ALL gated by
calibrated Jev judgments, with a contextTokens-style budget enforced in code, a
labeled eval harness proving each gate, cross-harness adapters, and a live
playground. That is the gap.

## What shape would be star-worthy?

Evidence from the scan: the repos that stand out all have evals (invalidate,
jev-recall with 238-memory bench, jevmem with eval dir) and the top Jev-context
repo (fast-jev-compaction, 4,548 stars) is a drop-in plugin, not a framework.
Star-worthy shape: a drop-in SDK (Honcho-compatible client: same card-like
objects, same two-layer injection, same token budget) PLUS a thin server/MCP
option for non-Python harnesses, PLUS a labeled eval harness runnable with one
command, PLUS a live playground replaying real runs. SDK gets adoption, eval
gets trust, playground gets stars. Jev-fit is ideal: all four gates (admit,
retrieve, invalidate, inject) are parallel single-snap judgments, one request
per turn, at roughly INR 0.002 per item.

## 3 candidate problem statements, ranked by realness x Jev-fit x GitHub-hugeness

1. Honcho-shaped full-lifecycle Jev memory SDK + server with budget-gated
   injection and a one-command labeled eval harness. Why: direct, demonstrable
   contrast with the reference platform; every gate is a Jev-native judgment;
   nothing above covers more than one gate.
2. Universal Jev retrieval-rerank adapter that plugs into any store (mem0,
   Honcho, Chroma, SQLite) with a published bench. Why: embeddings-miss pain is
   real and jev-recall already proved the demo-plus-bench pattern; gap is making
   it store-agnostic instead of standalone.
3. Forgetting-as-a-service: lease + supersede sidecar (MCP server) that bolts
   onto any memory store. Why: stale facts are the top memory complaint and
   invalidate validated the lease idea at small scale; gap is productionizing it
   with human override and Postgres ledger.
