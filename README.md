# UnclutteredMemory

Full-lifecycle agent memory: Jev-gated writes, Jev-reranked reads, signed provenance, and proof you can run.

Agent memory today saves everything, understands nothing about what matters, and stuffs too much into context.
UnclutteredMemory is the layer where cheap typed Jev judgments gate every write and rank every read, code owns all
budgets and math, and a frozen labeled eval plus a poison gauntlet measure every claim.

Status: phase 1 (SDK gates + calibration + frozen eval) in progress. Design frozen by two independent judges
(deepseek-v4.1-flash, glm-5.3-flash), every axis 8/10 or higher. See docs/.

## What is inside

- src/gate.py: admit triage (choice) + importance (score) + sensitive guard (noul), one batched call, uncalibrated by default
- src/store.py: SQLite + sqlite-vec, content-hash dedupe, provenance and trust tiers, soft tombstones
- src/supersede.py: code-ordered pairs, Jev relation vote, paired-judge agreement before destructive acts
- src/recall.py: topical noul rerank, gate plus band plus cap, deterministic prefilter
- src/inject.py: Honcho-order packing, whole-card truncation, fixed token budget
- src/calibrate.py: per-task wizard, fingerprinted threshold registry, train-only tuning
- src/server.py + MCP tools: write/recall/context/admin, per-user caps, kill switch
- eval/: 7 suites, ~640 labeled cases, frozen 50/50 split, red team, one command
- playground/: 5 static pages (parked to phase 4)

## Commands

unclutter run        run the frozen eval
unclutter calibrate  tune thresholds on train split only
unclutter redteam    fire the poison gauntlet, print survival rate
unclutter gauntlet --record   record the demo video

## Design

docs/master-plan.md is the frozen plan: claim, attack ledger, never-say list, phased go/no-go.
research/ holds the evidence: failure modes, Honcho deep dive, market landscape, Jev capability map, gap scan.
prompts/ holds both judge verdicts for every round.

## License

MIT (decided at first public release; repo is private until then).
Honcho (github.com/plastic-labs/honcho) informed object shapes and injection semantics; its license and
attribution are preserved where shapes are borrowed.