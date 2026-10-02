"""P3 MCP tests: tools.json schema doc plus the working stdio adapter.

The adapter is spawned as a real subprocess and driven over stdio
with JSON-RPC-ish lines (tools/list, tools/call) for admit, recall,
inject, and review. A drift test pins tools.json to the adapter map.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "mcp" / "adapter.py"
TOOLS_JSON = REPO / "mcp" / "tools.json"

STORE_TEXT = "standup 9am daily"
QUAR_TEXT = "The weather was nice yesterday in some vague way"


def _session(lines, timeout=30):
    proc = subprocess.Popen(
        [sys.executable, str(ADAPTER), "--db", ":memory:"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        out, _err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _call(rid, name, args):
    return json.dumps({"id": rid, "method": "tools/call",
                       "params": {"name": name, "arguments": args}})


def test_tools_json_lists_four_scoped_tools():
    doc = json.loads(TOOLS_JSON.read_text(encoding="utf-8"))
    names = sorted(t["name"] for t in doc["tools"])
    assert names == ["admit", "inject", "recall", "review"]
    for tool in doc["tools"]:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "user" in schema["required"], \
            "every tool must require a user (per-user scoping)"


def test_adapter_list_call_roundtrip():
    resps = _session([
        json.dumps({"id": 1, "method": "tools/list"}),
        _call(2, "admit", {"user": "alice", "text": STORE_TEXT,
                            "source": "chat"}),
        _call(3, "recall", {"user": "alice",
                             "query": "standup daily"}),
        _call(4, "inject", {"user": "alice",
                             "query": "standup daily"}),
        _call(5, "review", {"user": "alice"}),
    ])
    by_id = {r.get("id"): r for r in resps}
    assert sorted(by_id) == [1, 2, 3, 4, 5]
    assert sorted(t["name"] for t in by_id[1]["result"]["tools"]) == \
        ["admit", "inject", "recall", "review"]
    admit = by_id[2]["result"]
    assert admit["action"] == "STORE"
    assert admit["_status"] == 200
    recall = by_id[3]["result"]
    assert STORE_TEXT in recall["texts"]
    inject = by_id[4]["result"]
    assert STORE_TEXT in inject["context"]
    assert by_id[5]["result"]["count"] == 0


def test_adapter_review_shows_quarantine_scoped():
    resps = _session([
        _call(1, "admit", {"user": "alice", "text": QUAR_TEXT,
                            "source": "chat"}),
        _call(2, "review", {"user": "alice"}),
        _call(3, "review", {"user": "bob"}),
    ])
    by_id = {r.get("id"): r for r in resps}
    assert by_id[1]["result"]["action"] == "QUARANTINE"
    assert by_id[2]["result"]["count"] == 1
    assert by_id[2]["result"]["quarantined"][0]["text"] == QUAR_TEXT
    assert by_id[3]["result"]["count"] == 0


def test_adapter_unknown_tool_and_method_are_errors():
    resps = _session([
        _call(1, "nope", {"user": "u"}),
        json.dumps({"id": 2, "method": "nope"}),
        _call(3, "admit", {"text": "no user here"}),
    ])
    by_id = {r.get("id"): r for r in resps}
    assert "error" in by_id[1]
    assert "error" in by_id[2]
    assert by_id[3]["result"]["isError"] is True
    assert by_id[3]["result"]["_status"] == 400
