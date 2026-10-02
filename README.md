# UnclutteredMemory

Memory that proves itself: a tiny typed judge at the door of agent memory.

- `src/uncluttered_memory/gate.py` — one batched judgment, code enforces drop/quarantine/store
- `src/uncluttered_memory/store.py` — SQLite + provenance + tombstones, never rewrites
- `src/uncluttered_memory/recall.py` — 0.58 gate, 45% band, cap 8, code packs
- `eval/cases.py` — frozen cases, tuning on these is a hard error

Run: `python3 -m pytest tests/`
