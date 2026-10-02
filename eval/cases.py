"""Frozen eval cases. Format locked: tuning on these is a hard error."""
import json

CASES = [
    {"text": "My stop-loss is 8%", "expect": "STORE"},
    {"text": "Buy the whole exchange lol", "expect": "DROP"},
    {"text": "ok", "expect": "DROP"},
    {"text": "I am Batman", "expect": "DROP"},
    {"text": "Rahul's number is 98xxx", "expect": "DROP"},
]


def save(path):
    with open(path, "w") as f:
        for c in CASES:
            f.write(json.dumps(c) + "\n")
