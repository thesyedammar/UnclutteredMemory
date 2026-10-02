"""MCP stdio adapter: tools/list + tools/call over the real Store/Gate.

Protocol: one JSON object per stdin line, one JSON response per stdout
line. Requests:

  {"id": 1, "method": "tools/list"}
  {"id": 2, "method": "tools/call",
   "params": {"name": "admit", "arguments": {"user": "u", "text": "..."}}}

Tool names map to MemoryApp ops: admit -> admit, recall -> recall,
inject -> inject, review -> review. Every tool requires a user and is
scoped to it; the kill switch and rate caps from server.py apply here
too, reported as {"isError": true, ...} with the HTTP-style status in
"_status" (503 killed, 429 rate or judge-halted, 400 bad input).

Judge: offline RuleJudge by default (documented stub, same as the
eval). A live Jev judge is only wired when the operator passes
--live-jev with HERMES_CUSTOM_OPENCODE_AI_API_KEY set; there is no
fallback model on 429 in either mode.

Run: python3 mcp/adapter.py [--db PATH] [--kill-file PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from uncluttered_memory.gate import RuleJudge  # noqa: E402
from uncluttered_memory.server import MemoryApp, RateLimiter  # noqa: E402
from uncluttered_memory.store import Store  # noqa: E402

TOOLS_FILE = Path(__file__).resolve().parent / "tools.json"

TOOL_TO_OP = {"admit": "admit", "recall": "recall",
              "inject": "inject", "review": "review"}


def load_tools() -> dict:
    return json.loads(TOOLS_FILE.read_text(encoding="utf-8"))


def build_app(db_path: str, kill_file=None) -> MemoryApp:
    if db_path != ":memory:" and str(Path(db_path).parent) not in ("", "."):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return MemoryApp(Store(db_path), RuleJudge(), RateLimiter(),
                     kill_file=kill_file)


def handle_request(app: MemoryApp, req: dict):
    rid = req.get("id")
    method = req.get("method")
    if method == "tools/list":
        return {"id": rid, "result": load_tools()}
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in TOOL_TO_OP:
            return {"id": rid, "error": "unknown tool %r (want %s)"
                    % (name, sorted(TOOL_TO_OP))}
        status, body = app.handle(TOOL_TO_OP[name], args,
                                  raw_chars=len(json.dumps(args)))
        body = dict(body)
        body["_status"] = status
        if status >= 400:
            body["isError"] = True
        return {"id": rid, "result": body}
    return {"id": rid, "error": "unknown method %r (want tools/list, "
                                "tools/call)" % (method,)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="UnclutteredMemory MCP stdio "
                                             "adapter (offline RuleJudge)")
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--kill-file", default=None)
    args = ap.parse_args(argv)
    app = build_app(args.db, args.kill_file)
    tools = load_tools()
    names = sorted(t["name"] for t in tools["tools"])
    assert names == sorted(TOOL_TO_OP), \
        "tools.json drifted from the adapter map: %s" % names
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps({"id": None, "error": "stdin line "
                                                              "must be "
                                                              "JSON"}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps(handle_request(app, req)) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
