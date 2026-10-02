"""Minimal HTTP server over the real Store/Gate (stdlib only, no new deps).

Four endpoints, all JSON, all per-user scoped (every call requires a
"user" string and every store read/write is scoped to it):

  POST /admit   {"user", "text", "source"} -> STORE / DROP / QUARANTINE
  POST /recall  {"user", "query"} -> scored live rows for that user, packed
  POST /inject  {"user", "query"} or {"user", "cards": [[text, score]]}
  GET  /status?user=...  or  POST /status {"user"} -> scoped counts

Safety, in request order:

1. Kill switch: env UNCLUTTER_KILL_SWITCH=1 (or a kill file whose
   path comes from --kill-file / UNCLUTTER_KILL_FILE) makes every
   endpoint refuse with HTTP 503 and a clear message. Checked first,
   so a killed server neither stores nor spends budget.
2. Per-user scoping: a missing or empty user is HTTP 400, nothing runs.
3. Rate caps: a per-minute call budget and a per-minute request-char
   budget (defaults in thresholds.py) enforced per server instance.
   Over budget is HTTP 429 with a retry_after hint plus one
   structured log line; the refused call stores and quarantines
   nothing.
4. Judge-halt degrade: when the judge raises the JevError family
   (rate limit, bad key, transport, malformed answer), Store.admit
   quarantines the item and this server answers HTTP 429 with
   quarantined=true and the quarantine id, so the caller knows the
   item is held for review, not dropped and not voted by a stub.
   A gate-decided QUARANTINE (stop branch, low confidence) is the
   normal disposition and answers HTTP 200. There is no fallback
   model anywhere on this path.

Recall scoring is the same surface-text signal as the offline read
path (token Jaccard between query and stored text), ranked by
Recall.select and packed by code budgets. It finds near wording,
not deep paraphrase; an empty list is the loud miss, by design.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import thresholds as th
from .gate import Gate
from .inject import Injector
from .jev_client import JevError, RateLimited
from .recall import Recall
from .store import Store, token_jaccard

_LOG = logging.getLogger(__name__)

KILL_ENV = "UNCLUTTER_KILL_SWITCH"
KILL_FILE_ENV = "UNCLUTTER_KILL_FILE"
KILL_TRUTHY = {"1", "true", "yes", "on"}

JUDGE_HALTED_REASON = "judge-halted"


def kill_switch_active(kill_file=None) -> tuple:
    """(active, message). Env flag or kill file; message names the source."""
    import os
    if os.environ.get(KILL_ENV, "").strip().lower() in KILL_TRUTHY:
        return True, ("kill switch active: memory server refusing all "
                      "requests (env %s is set)" % KILL_ENV)
    path = kill_file or os.environ.get(KILL_FILE_ENV, "").strip() or None
    if path:
        import os.path as _p
        if _p.exists(path):
            return True, ("kill switch active: memory server refusing all "
                          "requests (kill file %s exists)" % path)
    return False, ""


class RateLimiter:
    """Rolling-window call + char budgets. Thread safe, clock injectable."""

    def __init__(self, calls_per_min: int = th.RATE_LIMIT_CALLS_PER_MIN,
                 chars_per_min: int = th.RATE_LIMIT_CHARS_PER_MIN,
                 window_secs: int = th.RATE_LIMIT_WINDOW_SECS,
                 clock=None):
        self.calls_per_min = calls_per_min
        self.chars_per_min = chars_per_min
        self.window = window_secs
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._calls: list = []
        self._chars: list = []

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._calls = [t for t in self._calls if t > cutoff]
        self._chars = [(t, n) for t, n in self._chars if t > cutoff]

    def remaining(self) -> dict:
        with self._lock:
            self._prune(self._clock())
            used_chars = sum(n for _, n in self._chars)
            return {"calls_remaining":
                    max(0, self.calls_per_min - len(self._calls)),
                    "chars_remaining":
                    max(0, self.chars_per_min - used_chars)}

    def check(self, n_chars: int) -> tuple:
        """Consume budget. Returns (ok, retry_after_secs).

        The backoff is computed from the true oldest entry still
        inside the window: the minimum timestamp across every
        recorded call and every recorded char charge. An earlier
        version read only the first entry of each list, which
        understates the wait whenever histories are not
        time-ordered. With no entries in the window (a single
        request larger than the whole char budget) there is no
        oldest entry, so the full window is reported.
        """
        with self._lock:
            now = self._clock()
            self._prune(now)
            used_chars = sum(n for _, n in self._chars)
            if (len(self._calls) >= self.calls_per_min
                    or used_chars + n_chars > self.chars_per_min):
                entries = list(self._calls) + [t for t, _ in self._chars]
                oldest = min(entries) if entries else now
                return False, max(1, int(self.window - (now - oldest)) + 1)
            self._calls.append(now)
            self._chars.append((now, n_chars))
            return True, 0


class MemoryApp:
    """Endpoint logic without HTTP: shared by the server and the MCP adapter.

    store: the real Store. judge: a JudgeClient (offline RuleJudge in
    tests and the default serve path; a live Jev judge only when the
    operator wires one explicitly). limiter: RateLimiter. kill_file:
    optional path whose existence refuses every call. live_pair: an
    optional live dual-Jev relation pair for the auto-activation
    bridge (None means the offline committee only, no network).
    """

    def __init__(self, store: Store, judge, limiter=None, kill_file=None,
                 live_pair=None):
        self.store = store
        self.judge = judge
        self.limiter = limiter or RateLimiter()
        self.kill_file = kill_file
        # The auto bridge live path shares the server per-minute
        # budget, so committee votes cost budget like any request;
        # offline votes cost nothing. Pre-wired store budgets are
        # respected, never overwritten.
        if getattr(store, "rate_limiter", None) is None:
            store.rate_limiter = self.limiter
        if live_pair is not None:
            store.auto_live_pair = live_pair
        self.recall = Recall()
        self.injector = Injector()
        # Serializes handler threads onto the one Store connection.
        self._lock = threading.Lock()

    def _refuse_log(self, op: str, user: str, detail: str) -> None:
        _LOG.error(json.dumps({
            "time": time.time(),
            "op": op,
            "user": user,
            "error_type": "RateBudgetExceeded",
            "detail": detail,
        }, sort_keys=True))

    def handle(self, op: str, payload: dict, raw_chars: int = 0) -> tuple:
        """Returns (http_status, body_dict). Never raises on bad input."""
        killed, kill_msg = kill_switch_active(self.kill_file)
        if killed:
            return 503, {"error": kill_msg, "refused": op}
        user = (payload.get("user") or "") if isinstance(payload, dict) else ""
        if not isinstance(user, str) or not user.strip():
            return 400, {"error": "a non-empty user is required on every "
                                  "call (per-user scoping); got none"}
        user = user.strip()
        if op not in ("admit", "recall", "inject", "status", "review"):
            return 400, {"error": "unknown endpoint %r (want admit, recall, "
                                  "inject, status)" % op}
        ok, retry_after = self.limiter.check(raw_chars)
        if not ok:
            detail = ("per-minute budget exceeded "
                      "(%d calls or %d chars per %ds)"
                      % (self.limiter.calls_per_min,
                         self.limiter.chars_per_min, self.limiter.window))
            self._refuse_log(op, user, detail)
            return 429, {"error": "rate budget exceeded: " + detail,
                         "retry_after_secs": retry_after,
                         "rate_limited": True, "quarantined": False}
        try:
            with self._lock:
                if op == "admit":
                    return self._admit(user, payload)
                if op == "recall":
                    return self._recall(user, payload)
                if op == "inject":
                    return self._inject(user, payload)
                if op == "status":
                    return self._status(user)
                return self._review(user, payload)
        except JevError as e:
            # Judge halted outside Store.admit (recall/inject never call
            # the judge today; this arm guards future judge-on-read
            # paths): halt honestly, never stub in place of the judge.
            return 429, {"error": "judge halted: %s" % e,
                         "rate_limited": isinstance(e, RateLimited),
                         "quarantined": False}

    def _live_id(self, user: str, text: str):
        for fid, old_text, *_ in self.store.live(user):
            if old_text == text:
                return fid
        return None

    def _latest_qid(self, user: str, text: str):
        found = None
        for qid, qtext, reason in self.store.quarantined(user):
            if qtext == text and (found is None or qid > found[0]):
                found = (qid, reason)
        return found

    def _admit(self, user: str, payload: dict) -> tuple:
        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return 400, {"error": "admit needs a non-empty text string"}
        source = payload.get("source", "")
        if not isinstance(source, str):
            return 400, {"error": "admit source must be a string"}
        action = self.store.admit(text, source, Gate(self.judge), user)
        if action == "STORE":
            return 200, {"action": "STORE", "user": user,
                         "fact_id": self._live_id(user, text),
                         "autospot": self.store.last_autospot}
        if action == "DROP":
            return 200, {"action": "DROP", "user": user}
        found = self._latest_qid(user, text)
        qid, reason = found if found else (None, "")
        if reason == JUDGE_HALTED_REASON:
            return 429, {"action": "QUARANTINE", "user": user,
                         "quarantined": True, "degraded": True, "qid": qid,
                         "reason": ("judge halted (rate limit, bad key, "
                                    "transport, or malformed answer); item "
                                    "held in quarantine for human review, "
                                    "never voted by a stub")}
        return 200, {"action": "QUARANTINE", "user": user,
                     "quarantined": True, "qid": qid, "reason": reason}

    def _score_live(self, user: str, query: str) -> list:
        scored = []
        for _fid, text, *_ in self.store.live(user):
            scored.append((text, token_jaccard(query, text)))
        scored.sort(key=lambda kv: -kv[1])
        return scored

    def _recall(self, user: str, payload: dict) -> tuple:
        query = payload.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return 400, {"error": "recall needs a non-empty query string"}
        scored = self._score_live(user, query)
        texts = self.recall.select(scored)
        return 200, {"user": user, "query": query,
                     "scored": [{"text": t, "score": round(s, 4)}
                                for t, s in scored],
                     "texts": texts,
                     "packed": self.recall.pack(texts)}

    def _inject(self, user: str, payload: dict) -> tuple:
        cards = payload.get("cards")
        if cards is not None:
            if (not isinstance(cards, list) or
                    not all(isinstance(c, (list, tuple)) and len(c) == 2
                            for c in cards)):
                return 400, {"error": "inject cards must be a list of "
                                      "[text, score] pairs"}
            try:
                norm = [(str(t), float(s)) for t, s in cards]
            except (TypeError, ValueError):
                return 400, {"error": "inject card scores must be numbers"}
        else:
            query = payload.get("query", "")
            if not isinstance(query, str) or not query.strip():
                return 400, {"error": "inject needs cards or a non-empty "
                                      "query string"}
            norm = self._score_live(user, query)
        context = self.injector.pack(norm)
        return 200, {"user": user, "context": context,
                     "cards_used": len(context.splitlines()) if context
                     else 0,
                     "budget_chars": self.injector.budget}

    def _status(self, user: str) -> tuple:
        return 200, {"user": user,
                     "live": len(self.store.live(user)),
                     "quarantined": len(self.store.quarantined(user)),
                     "conflicts": len(self.store.conflicts(user)),
                     "error_count": self.store.error_count,
                     "kill_active": kill_switch_active(self.kill_file)[0],
                     "rate": self.limiter.remaining()}

    def _review(self, user: str, payload: dict) -> tuple:
        items = [{"qid": qid, "text": text, "reason": reason}
                 for qid, text, reason in self.store.quarantined(user)]
        return 200, {"user": user, "quarantined": items,
                     "count": len(items)}


class _Handler(BaseHTTPRequestHandler):
    app: MemoryApp  # set by serve() on the bound subclass

    def log_message(self, format, *args):  # keep test output clean
        _LOG.debug(format % args)

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _op(self):
        path = urlparse(self.path).path.strip("/")
        if path in ("admit", "recall", "inject", "status", "review"):
            return path
        return None

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(max(0, n))
        if not raw:
            return {}, 0
        try:
            return json.loads(raw.decode("utf-8")), len(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, 0

    def do_POST(self):  # noqa: N802 (http.server names the method)
        op = self._op()
        if op is None:
            self._send(404, {"error": "unknown path (want /admit, /recall, "
                                      "/inject, /status)"})
            return
        payload, n_chars = self._read_json()
        if payload is None:
            self._send(400, {"error": "request body must be JSON"})
            return
        status, body = self.app.handle(op, payload, n_chars)
        self._send(status, body)

    def do_GET(self):  # noqa: N802 (http.server names the method)
        parsed = urlparse(self.path)
        op = parsed.path.strip("/")
        if op not in ("status", "review"):
            self._send(404,
                       {"error": "GET serves /status and /review only "
                                 "(POST for admit, recall, inject)"})
            return
        qs = parse_qs(parsed.query)
        payload = {"user": (qs.get("user") or [""])[0]}
        status, body = self.app.handle(op, payload, 0)
        self._send(status, body)


def serve(host: str, port: int, store: Store, judge, kill_file=None,
          limiter=None) -> ThreadingHTTPServer:
    """Build (not run) a ThreadingHTTPServer over the real store/gate."""
    app = MemoryApp(store, judge, limiter=limiter, kill_file=kill_file)
    handler = type("BoundHandler", (_Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)
