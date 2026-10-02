"""Write-path gate: one batched judgment call, enforcement in code.

The judge answers typed questions per line. Code owns every
decision after that: drop / quarantine / store. No meaning in the ifs.
Unseen or low-confidence input fails closed to quarantine, never an
exception. RuleJudge is an offline heuristic stub, not Jev.

Every decision cutoff is a parameter of Gate.decide whose default
lives in thresholds.py; no numeric decision boundary is hardcoded in
this module's logic paths. The reason strings echo the effective
cutoff so an override is visible in the decision record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import thresholds as th


@dataclass
class GateVote:
    durable: float  # 0..1 durable-or-chatter
    importance: int  # 1..5
    stop: float  # 0..1 stop-or-pass (high = block)
    play: float = 0.0  # 0..1 playful/joke signal
    sensitive: float = 0.0  # 0..1 private-data signal
    conf: float = 1.0  # 0..1 judge confidence; low means abstain


@dataclass
class GateDecision:
    action: str  # STORE, QUARANTINE, DROP
    reasons: list = field(default_factory=list)


class JudgeClient:
    """Judge protocol. The base fails closed; real judges override vote()."""

    def vote(self, text: str, neighbors: list, facts: list) -> GateVote:
        return GateVote(0.5, 2, 0.5, conf=0.0)


class FakeJudge(JudgeClient):
    """Deterministic stub for branch tests. Missing keys fail closed."""

    def __init__(self, votes: dict):
        self.votes = votes

    def vote(self, text, neighbors, facts):
        v = self.votes.get(text)
        if v is None:
            return GateVote(0.5, 2, 0.5, conf=0.0)
        return v


# Word-ish laugh tokens only: "lollipop" must not read as play.
LAUGH_RE = re.compile(r"(?<![a-z])(?:lol|lmao|rofl|(?:ha){2,})(?![a-z])")
FILLER = {"ok", "k", "fine", "sure", "yes", "no", "hey", "hi", "hello",
          "thanks", "thx", "cool", "nice", "yo", "okay", "okey", "kk",
          "got it", "sounds good", "will do"}
CONTACT = ("number", "phone", "mobile", "ssn", "otp", "card", "account",
           "address", "email", "passcode", "password")
DURABLE_MARK = ("prefer", "standup", "deadline", "allerg", "stop-loss",
                "stoploss", "limit", "always", "never", "%")

# RuleJudge vote levels: heuristic stub outputs, not decision cutoffs.
# The cutoffs that read these live in thresholds.py.
FILLER_LEVELS = (0.05, 1, 0.1)
FILLER_CONF = 0.9
PLAY_LEVELS = (0.3, 1, 0.2)
PLAY_SIGNAL = 0.85
PLAY_CONF = 0.8
SENSITIVE_LEVELS = (0.6, 2, 0.1)
SENSITIVE_SIGNAL = 0.9
SENSITIVE_CONF = 0.8
DURABLE_DURABLE = 0.9
DURABLE_STOP = 0.05
DURABLE_CONF = 0.8
DURABLE_HARD_IMPORTANCE = 5
DURABLE_SOFT_IMPORTANCE = 4
UNCERTAIN_LEVELS = (0.5, 2, 0.4)
UNCERTAIN_CONF = 0.2
HARD_MARKS = ("%", "stop-loss", "deadline", "allerg", "limit")

# Offline importance rubric: 5/4 are earned from compositional signals
# documented here, never from one marker substring alone.
#
# VITAL (5) means forgetting has a concrete cost: bodily harm, money or
# housing at risk, a legal or immigration consequence, or a time-bound
# duty tied to a real date. Evidence is a pairing, not a word: an
# obligation noun (deadline, renewal, filing, expiry, cutoff, due date)
# PLUS a date expression; a legal term (visa, passport, court, custody,
# hearing, immigration) PLUS a date or a procedural noun (interview,
# papers); a risk cap (stop-loss with a percent, or a limit with lots,
# percent, or %); a jeopardy term (evict, forfeit, foreclose,
# repossess, nonrefundable); an acute-care term (epinephrine,
# anaphylaxis, insulin, inhaler, seizure, overdose, bacteria,
# contamination, poison, or a standing allergy record, since
# forgetting an allergy risks exposure); or a care term (pill, medication, dose,
# prescription) inside a harm clause ("or she faints"). A bare marker
# with no date, cost, or care pairing earns nothing: a deadline poster
# hanging crooked is scenery, not a duty, so it reads 2.
#
# ROUTINE (4) means a reusable standing fact: a standing preference or
# habit word (prefer, standup) or a standing rule (always, never); a
# recurrence ("every" with a weekday, daypart, or visit; daily,
# weekly, twice a year); a schedule verb (opens, closes, leaves,
# meets, resets, clears) with a clock time (digits, o'clock, half
# past, quarter to/past) or a named day; a named slot; a capacity or
# rate (terabyte, seats, an hour, per visit); a kept-object location
# (key, charger, adapter, notes, drive with hangs, lies, sits, lives,
# waits, behind, under, inside, above); or a date of record
# (birthday, anniversary with a month or day).
#
# Anything with a marker or digit but neither vital nor routine
# structure is a marker-bearing observation and reads 2 with low
# confidence, so the admit gate quarantines instead of storing it.


def _laugh(low: str) -> bool:
    return LAUGH_RE.search(low) is not None


def _identity_claim(raw: str, low: str) -> bool:
    """Proper-noun 'I am X' with no durable markers reads as play.

    Casefold-insensitive: 'i am zorro' and 'I am Zorro' both read
    as identity claims. Casing alone never distinguishes a name, so
    the match runs on raw.casefold() and the name check accepts any
    leading letter via casefold instead of requiring an uppercase
    first letter. The low argument is accepted for call compatibility
    and is not trusted for the decision.
    """
    folded = raw.casefold()
    if re.fullmatch(r"i am ([a-z][a-z ]{0,20})", folded) is None:
        return False
    if re.search(r"\d", raw) is not None:
        return False
    ent = raw.strip()[4:].strip()
    return bool(ent) and ent[0].casefold().isalpha()


def _sensitive(low: str) -> bool:
    if "xxx" in low or "****" in low:
        return True
    if re.search(r"\b\d{6,}\b", low) is not None:
        return True
    return any(w in low for w in CONTACT) and re.search(r"\d", low) is not None


def _durable(low: str) -> bool:
    if "%" in low or re.search(r"\d", low) is not None:
        return True
    return any(w in low for w in DURABLE_MARK)


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "weekday", "weekdays")
_MONTHS = ("january", "february", "march", "april", "may", "june",
           "july", "august", "september", "october", "november",
           "december", "spring", "summer", "autumn", "winter")
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth",
             "seventh", "eighth", "ninth", "tenth", "eleventh",
             "twelfth", "thirteenth", "fourteenth", "fifteenth",
             "sixteenth", "seventeenth", "eighteenth", "nineteenth",
             "twentieth", "twenty-first", "thirtieth", "thirty-first",
             "last")
_TERM_END = ("end of quarter", "last day of term", "end of term")
_NAMED_DAYS = _WEEKDAYS + _MONTHS + ("today", "tomorrow", "yesterday",
                                    "tonight", "holiday", "holidays")

_CLOCK_RE = re.compile(r"\d|o'clock|half past|quarter (to|past)")

_OBLIGATION = ("deadline", "renewal", "filing", "expiry", "expire",
               "cutoff", "due date", "enrollment")
_LEGAL = ("visa", "passport", "court", "custody", "hearing",
         "immigration", "asylum")
_PROCEDURE = ("interview", "papers", "paperwork", "office", "notice")
_JEOPARDY = ("evict", "forfeit", "foreclos", "repossess",
            "nonrefundable", "overdraft")
_ACUTE = ("epinephrine", "epipen", "anaphylaxis", "insulin", "inhaler",
         "seizure", "overdose", "bacteria", "contaminat", "poison",
         "allerg")
_CARE = ("pill", "pills", "medication", "dose", "prescription",
        "antibiotic")
_HARM_CLAUSE_RE = re.compile(
    r"\bor (she|he|they|it|you) "
    r"(faint|faints|collapse|collapses|die|dies|seize|seizes|choke)\b")


def _date_expr(low: str) -> bool:
    if _CLOCK_RE.search(low) is not None:
        return True
    if any(w in low for w in _NAMED_DAYS):
        return True
    if any(w in low for w in _ORDINALS):
        return True
    return any(p in low for p in _TERM_END)


def _vital(low: str) -> bool:
    if any(w in low for w in _ACUTE):
        return True
    if any(w in low for w in _CARE) and _HARM_CLAUSE_RE.search(low):
        return True
    if any(w in low for w in _JEOPARDY):
        return True
    if (("stop-loss" in low or "stoploss" in low or "stop loss" in low)
            and "%" in low):
        return True
    if (("limit" in low or " cap " in (" " + low + " ")) and
            ("lots" in low or "percent" in low or "%" in low)):
        return True
    if any(w in low for w in _LEGAL) and (
            _date_expr(low) or any(w in low for w in _PROCEDURE)):
        return True
    if any(w in low for w in _OBLIGATION) and _date_expr(low):
        return True
    return False


_ROUTINE_WORDS = ("prefer", "standup", "always", "never", "slot",
                  "daily", "weekly")
_SCHEDULE_VERBS = ("opens", "closes", "leaves", "meets", "runs",
                   "starts", "resets", "clears", "moved", "moves")
_CAPACITY = ("terabyte", "terabytes", "gigabyte", "gigabytes",
             "megabyte", "seat", "seats", "capacity", "an hour",
             "per hour", "twice a", "per visit", "tenth visit")
_KEPT_OBJECTS = ("key", "keys", "charger", "adapter", "wallet",
                 "documents", "drive", "notes", "contact", "medication",
                 "remote", "router")
_LOCATIVE = ("hangs", "lies", "sits", "lives", "live", "waits",
             "behind", "under", "inside", "above")
_RECORD = ("birthday", "anniversary")


def _routine(low: str) -> bool:
    if any(w in low for w in _ROUTINE_WORDS):
        return True
    if "every" in low and (
            _date_expr(low) or "visit" in low or "trip" in low
            or "morning" in low or "evening" in low):
        return True
    if any(v in low for v in _SCHEDULE_VERBS) and (
            _CLOCK_RE.search(low) is not None
            or any(w in low for w in _NAMED_DAYS)):
        return True
    if any(w in low for w in _CAPACITY):
        return True
    if (any(w in low for w in _KEPT_OBJECTS)
            and any(w in low for w in _LOCATIVE)):
        return True
    if any(w in low for w in _RECORD) and _date_expr(low):
        return True
    return False


class RuleJudge(JudgeClient):
    """Offline heuristic keyed by text features, never by exact strings.

    Not Jev and never labeled as Jev. Anything it cannot read fails
    closed to a low-confidence vote, which the gate quarantines.
    """

    def vote(self, text, neighbors=None, facts=None):
        t = " ".join(text.split())
        low = t.lower()
        if low in FILLER or len(t) <= 2:
            return GateVote(*FILLER_LEVELS, conf=FILLER_CONF)
        if _laugh(low) or _identity_claim(t, low):
            return GateVote(*PLAY_LEVELS, play=PLAY_SIGNAL, conf=PLAY_CONF)
        if _sensitive(low):
            return GateVote(*SENSITIVE_LEVELS, sensitive=SENSITIVE_SIGNAL,
                            conf=SENSITIVE_CONF)
        if _vital(low):
            return GateVote(DURABLE_DURABLE, DURABLE_HARD_IMPORTANCE,
                            DURABLE_STOP, conf=DURABLE_CONF)
        if _routine(low):
            return GateVote(DURABLE_DURABLE, DURABLE_SOFT_IMPORTANCE,
                            DURABLE_STOP, conf=DURABLE_CONF)
        return GateVote(*UNCERTAIN_LEVELS, conf=UNCERTAIN_CONF)


def _num(v: float) -> str:
    """Compact threshold rendering for reasons: 0.7 -> '0.7'."""
    return "%g" % v


class Gate:
    def __init__(self, judge: JudgeClient):
        self.judge = judge

    def decide(self, text: str, neighbors=None, facts=None,
               importance_min: int = th.IMPORTANCE_MIN,
               durable_min: float = th.DURABLE_MIN,
               stop_block: float = th.STOP_BLOCK,
               min_conf: float = th.MIN_CONF,
               play_drop: float = th.PLAY_DROP,
               sensitive_drop: float = th.SENSITIVE_DROP) -> GateDecision:
        v = self.judge.vote(text, neighbors or [], facts or [])
        if v.conf < min_conf:
            return GateDecision("QUARANTINE", ["uncertain-low-conf"])
        if v.play > play_drop:
            return GateDecision("DROP", ["play>" + _num(play_drop)])
        if v.sensitive > sensitive_drop:
            return GateDecision("DROP", ["sensitive>" + _num(sensitive_drop)])
        if v.stop >= stop_block:
            return GateDecision("QUARANTINE",
                                ["stop>=" + _num(stop_block)])
        if v.durable >= durable_min and v.importance >= importance_min:
            return GateDecision("STORE", ["durable+important"])
        return GateDecision("DROP", ["not-durable-or-trivial"])
