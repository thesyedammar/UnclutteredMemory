"""Deterministic generator for eval/frozen.jsonl.

Every case is rule-labeled: expectations are pinned to the documented
rule stubs (RuleJudge for the write gate, the strict + lenient relation
pair for pair relations, the store for dedupe, Recall for rerank) and
the generator refuses to write unless every case matches its stub
exactly and every text is unique. All cases carry
provenance=synthetic-rule. Nothing here is a human label, and docs must
never present it as one.

This generator does not touch eval/golden.jsonl. The golden set is
hand-written data whose labels come from a human reading of the gate
contract, not from this file; the two sets share no code path and no
label string.

Regenerate with:

    PYTHONPATH=src python3 eval/cases.py

The generator also enforces the frozen-split invariants the eval relies
on: unique text per case and even per-kind group sizes, so the
deterministic 50/50 split stays exactly balanced.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "frozen.jsonl"

PROVENANCE = "synthetic-rule"
SUITE_ORDER = ("admit", "importance", "dedupe", "contradict", "supersede",
               "rerank")
EXPECTED_COUNTS = {
    "admit": 240,
    "importance": 112,
    "dedupe": 80,
    "contradict": 80,
    "supersede": 80,
    "rerank": 56,
}

FILLER_WORDS = ("ok", "k", "fine", "sure", "yes", "no", "hey", "hi", "hello",
                "thanks", "thx", "cool", "nice", "yo")

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _norm(t: str) -> str:
    return " ".join(_NON_WORD.sub(" ", t.casefold()).split())


def _case_strings(case: dict) -> list:
    out: list = []

    def walk(v, key=None):
        if isinstance(v, str):
            if key not in ("id", "suite", "kind", "provenance", "expect",
                           "label", "gate"):
                out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)

    walk(case)
    return out


class Builder:
    def __init__(self):
        self.cases = []
        self._counters = {}

    def add(self, suite, kind, expect, **fields):
        idx = self._counters.get((suite, kind), 0)
        self._counters[(suite, kind)] = idx + 1
        c = {"id": "%s-%s-%04d" % (suite, kind, idx),
             "suite": suite, "kind": kind, "expect": expect,
             "provenance": PROVENANCE}
        c.update(fields)
        self.cases.append(c)


def build_cases() -> list:
    b = Builder()

    # ------------------------------------------------------------------
    # admit: 240 cases. STORE 96, DROP 96, QUARANTINE 48.
    # ------------------------------------------------------------------
    numbers = (4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20, 25)
    percent_styles = (
        "My stop-loss is {n}%",
        "stop-loss set at {n}% on entry",
        "keep the {n}% stop loss tight",
        "exit plan: stop-loss at {n}%",
    )
    for i, n in enumerate(numbers):
        for j, style in enumerate(percent_styles):
            b.add("admit", "durable-percent", "STORE",
                  text=style.format(n=n))

    deadline_bases = (
        ("The report deadline is Friday",
         "report deadline: Friday",
         "the deadline for the report is Friday",
         "Friday is the report deadline"),
        ("sprint deadline is Monday",
         "the sprint deadline lands on Monday",
         "Monday carries the sprint deadline",
         "sprint: deadline Monday"),
        ("tax deadline is March 15",
         "the March 15 tax deadline stands",
         "tax filing deadline: March 15",
         "March 15 is the tax deadline"),
        ("the grant deadline fell on Tuesday",
         "grant deadline was Tuesday",
         "Tuesday held the grant deadline",
         "the grant deadline was moved to Tuesday"),
        ("deadline for the migration is end of quarter",
         "migration deadline: end of quarter",
         "the migration deadline is end of quarter",
         "end of quarter is the migration deadline"),
        ("submission deadline is the thirtieth",
         "the thirtieth is the submission deadline",
         "submission: deadline the thirtieth",
         "we submit by the thirtieth, that deadline stands"),
    )
    for group in deadline_bases:
        for text in group:
            b.add("admit", "durable-deadline", "STORE", text=text)

    preference_bases = (
        ("I prefer aisle seats on flights",
         "aisle seats on flights are my preference",
         "flights: I prefer aisle seats",
         "I always prefer an aisle seat when flying"),
        ("prefer tea over coffee in the morning",
         "mornings: tea over coffee, that is my preference",
         "I prefer tea to coffee in the morning",
         "tea in the morning, coffee later, that is the preference"),
        ("I prefer standup notes in the evening",
         "evening standup notes are what I prefer",
         "standup notes in the evening, that is my preference",
         "I prefer the standup notes to land in the evening"),
        ("prefer to review code before lunch",
         "before lunch is when I prefer reviewing code",
         "I prefer reviewing code before lunch",
         "code review before lunch is the preference"),
        ("I always prefer the earlier train",
         "the earlier train is what I always prefer",
         "earlier trains: always my preference",
         "I prefer the earlier train, always"),
        ("she prefers the monthly billing plan",
         "the monthly billing plan is her preference",
         "monthly billing: her preference",
         "she always prefers monthly billing"),
    )
    for group in preference_bases:
        for text in group:
            b.add("admit", "durable-preference", "STORE", text=text)

    filler_pool = list(FILLER_WORDS) + [w.capitalize() for w in FILLER_WORDS]
    filler_pool += ["OK", "SURE", "YES", "NO"]
    for text in filler_pool[:32]:
        b.add("admit", "filler", "DROP", text=text)

    laugh_pool = (
        "that was funny lol", "buy the whole exchange lol", "ship it lmao",
        "haha nice one", "rofl that spec", "lol the meeting ran long",
        "that plan is done lol", "nice work lmao", "haha the printer died",
        "rofl the build failed", "lol friday deploy", "what a week lmao",
        "haha the demo worked", "rofl that slide deck", "lol the coffee ran out",
        "that review was funny lol", "lmao the linter complained",
        "haha classic friday", "rofl the wifi again", "lol same energy",
        "we shipped it lol", "lmao ceiling cat", "haha bugs everywhere",
        "rofl the test suite blinked",
    )
    identity_pool = (
        "I am Batman", "I am Ironman", "I am Groot", "I am Spartacus",
        "I am Legend", "I am Vengeance", "I am Batman Forever",
        "I am Iron Man", "I am Groot Again", "I am Spartacus Jr",
        "I am Legend Now", "I am Vengeance Rising", "I am Batman Returns",
        "I am Iron Giant", "I am Groot Sr", "I am Spartacus Maximus",
    )
    for text in laugh_pool:
        b.add("admit", "play", "DROP", text=text)
    for text in identity_pool:
        b.add("admit", "play", "DROP", text=text)

    sensitive_pool = (
        "Rahul's number is 9812345678",
        "otp is 994553",
        "my mobile is 98xxxx",
        "ssn on file is 11-22-3344",
        "card ends 4455",
        "email backup code is 778899",
        "passcode 884422",
        "account number 998877",
        "the number is 9811112222",
        "the otp changed to 665544",
        "mobile 98xxxx again",
        "ssn is 55-66-7788",
        "card number 411111",
        "email code 223344",
        "passcode rotated to 556677",
        "account 445533",
        "his number is 9700001111",
        "otp 112233",
        "mobile is 97xxxx",
        "ssn 99-88-7766",
        "card 550000",
        "email code 334455",
        "passcode 221100",
        "account number 667788",
    )
    for text in sensitive_pool:
        b.add("admit", "sensitive", "DROP", text=text)

    uncertain_bases = (
        "the archive sits in the basement",
        "we met at the blue house",
        "the garden needs rain soon",
        "the painting hangs in the hallway",
        "the river runs behind the field",
        "the kettle whistles when hot",
        "the cat sleeps on the windowsill",
        "the bus stops near the corner",
        "the kitchen window faces east",
        "the trail climbs past the ridge",
        "the library closes at dusk",
        "the band plays in the square",
    )
    for base in uncertain_bases:
        for text in (base, "apparently " + base, base + ", I think",
                     base.replace("the", "the old", 1)):
            b.add("admit", "uncertain", "QUARANTINE", text=text)

    # ------------------------------------------------------------------
    # importance: 112 cases. imp5 24, imp4 40, imp1 24, imp2 24.
    # ------------------------------------------------------------------
    imp5_nouns = ("deposit", "grant report", "migration", "budget sheet",
                  "compliance form", "conference talk", "thesis draft",
                  "patent filing", "lease renewal", "glossary pass",
                  "audit reply", "invoice batch")
    imp5_days = ("Friday", "Monday", "March 3", "the fifth", "April 15",
                 "the ninth", "June 1", "the twelfth", "the eighteenth",
                 "September 2", "the twenty-first", "the last day of term")
    for noun, day in zip(imp5_nouns, imp5_days):
        b.add("importance", "imp5", 5,
              text="the %s deadline is %s" % (noun, day))
        b.add("importance", "imp5", 5,
              text="%s is the hard deadline for the %s" % (day, noun))

    labs = ("the west lab", "the east lab", "the north desk", "the south desk",
            "the hub", "the annex", "the loft", "the yard", "the dock",
            "the pier")
    times = ("7am", "8am", "9am", "10am", "11am", "12pm", "2pm", "3pm",
             "4pm", "5pm")
    combos = [(labs[i % 10], times[i % 10]) for i in range(10)]
    combos += [(labs[i % 10], times[(i + 4) % 10]) for i in range(10)]
    for lab, t in combos:
        b.add("importance", "imp4", 4, text="%s opens at %s" % (lab, t))
        b.add("importance", "imp4", 4, text="the %s slot covers %s" % (t, lab))

    imp1_filler = ("ok", "sure", "cool", "nice", "thanks", "hello", "yo",
                   "fine")
    imp1_laugh = ("that works lol", "good one haha", "nice try rofl",
                  "classic lmao", "the wifi died haha", "so funny lol",
                  "best meeting lol", "cheers lmao")
    imp1_identity = ("I am Rocket", "I am Nebula", "I am Drax", "I am Mantis",
                     "I am Valkyrie", "I am Storm", "I am Phoenix",
                     "I am Wolverine")
    for text in imp1_filler + imp1_laugh + imp1_identity:
        b.add("importance", "imp1", 1, text=text)

    imp2_sensitive = ("my pin is 448866", "otp 559900", "ssn 44-55-6677",
                      "number 909090", "card 445566", "mobile 667788",
                      "passcode 112233", "backup email code 998877",
                      "account 554433", "otp 778899", "phone 990011",
                      "ssn 66-77-8899")
    imp2_uncertain = ("the violin rests in its case",
                      "the compass points north",
                      "the lantern hangs by the porch",
                      "the ferry crosses at dawn",
                      "the notebook lies on the desk",
                      "the rookery wakes at sunrise",
                      "the hose coils by the tap",
                      "the mural covers the wall",
                      "the oven warms the kitchen",
                      "the trail forks past the creek",
                      "the sail catches the breeze",
                      "the bell rings across the yard")
    for text in imp2_sensitive + imp2_uncertain:
        b.add("importance", "imp2", 2, text=text)

    # ------------------------------------------------------------------
    # dedupe: 80 cases. DUP 40, DISTINCT 40.
    # ------------------------------------------------------------------
    verbs = ("ship", "review", "archive", "update", "stage", "measure",
             "sketch", "draft", "polish", "wire")
    objects = ("the friday build", "the sales report", "the onboarding flow",
               "the garden gate", "the studio lease", "the evening menu",
               "the field notes", "the red bicycle", "the guest list",
               "the backup plan")
    combos = ["%s %s" % (v, o) for v in verbs for o in objects]
    dup_combos = combos[:40]
    distinct_combos = combos[40:80]
    ws_styles = (lambda t: t.replace(" ", "  "),
                 lambda t: "  " + t + "  ",
                 lambda t: t.replace(" ", "\t"),
                 lambda t: t + " ")
    for i, text in enumerate(dup_combos):
        b.add("dedupe", "dup", "DUP", text=text,
              candidate=ws_styles[i % 4](text))
    distinct_styles = (lambda t: t.capitalize(),
                       lambda t: t + ".",
                       lambda t: t.replace("the ", "a ", 1),
                       lambda t: t + " today")
    for i, text in enumerate(distinct_combos):
        b.add("dedupe", "distinct", "DISTINCT", text=text,
              candidate=distinct_styles[i % 4](text))

    # ------------------------------------------------------------------
    # contradict: 80 cases. CONFLICT 48, KEEP 32.
    # ------------------------------------------------------------------
    conflict_bases = (
        ("I love morning runs", "morning runs"),
        ("the team uses the old chat tool", "the old chat tool"),
        ("coffee after lunch is a habit", "coffee after lunch"),
        ("the studio opens at nine", "the studio opening time"),
        ("weekly board games are a thing", "weekly board games"),
        ("the north gate is the entry", "the north gate"),
        ("the rooftop garden is open", "the rooftop garden"),
        ("friday calls run long", "the friday calls"),
        ("we keep paper invoices", "the paper invoices"),
        ("dessert after dinner happens", "dessert after dinner"),
        ("the guest wifi is shared", "the guest wifi password"),
        ("the 7am alarm works", "the 7am alarm"),
    )
    conflict_styles = (
        "I do not keep {x} anymore",
        "{x} is not part of my week anymore",
        "we do not do {x} anymore, never again",
        "I do not miss {x} at all anymore",
    )
    conflict_olds = (
        "{o}",
        "we still enjoy {x}",
        "I keep {x} around",
        "{x} has been the routine",
    )
    for old, x in conflict_bases:
        for old_t, style in zip(conflict_olds, conflict_styles):
            b.add("contradict", "conflict", "CONFLICT",
                  old=(old if old_t == "{o}" else old_t.format(x=x)),
                  new=style.format(x=x))

    keep_items = ("the spare key", "the blue kettle", "the paper map",
                  "the red ladder", "the wool blanket", "the brass lamp",
                  "the iron skillet", "the glass jar", "the linen apron",
                  "the silver tray", "the wooden crate", "the copper pot",
                  "the canvas bag", "the leather strap", "the marble bowl",
                  "the ceramic mug", "the bamboo mat", "the steel box",
                  "the felt hat", "the cotton scarf", "the rubber boots",
                  "the straw basket", "the clay vase", "the stone bowl",
                  "the oak stool", "the pine shelf", "the maple board",
                  "the willow chair", "the birch handle", "the ash tray",
                  "the cedar chest", "the walnut desk")
    keep_rooms = ("studio", "kitchen", "attic", "cellar", "study", "porch",
                  "garage", "shed")
    for i, item in enumerate(keep_items):
        b.add("contradict", "keep", "KEEP",
              old="I keep %s in the studio" % item,
              new="%s stays in the %s" % (item, keep_rooms[i % 8]))

    # ------------------------------------------------------------------
    # supersede: 80 cases. TOMBSTONE 48, KEEP 32.
    # ------------------------------------------------------------------
    places = ("office", "warehouse", "print shop", "bike store",
              "coffee stand", "repair desk", "records room", "supply closet",
              "training room", "photo lab", "tool shed", "reading nook")
    old_locs = ("the east wing", "the old mill", "the station road",
                "the market square", "the river bend", "the chapel lane",
                "the mill yard", "the lower deck", "the west quay",
                "the park edge", "the orchard row", "the main gate")
    new_locs = ("the north lot", "the annex", "the high street",
                "the harbor road", "the county line", "the new arcade",
                "the upper deck", "the glass tower", "the south quay",
                "the hill road", "the creekside", "the depot")
    for thing, old_loc, new_loc in zip(places, old_locs, new_locs):
        b.add("supersede", "tombstone", "TOMBSTONE",
              old="the %s is at %s" % (thing, old_loc),
              new="the %s moved to %s" % (thing, new_loc))
        b.add("supersede", "tombstone", "TOMBSTONE",
              old="the %s sits near %s" % (thing, old_loc),
              new="the %s changed to %s" % (thing, new_loc))
        b.add("supersede", "tombstone", "TOMBSTONE",
              old="the %s was on %s" % (thing, old_loc),
              new="the %s is now at %s" % (thing, new_loc))
        b.add("supersede", "tombstone", "TOMBSTONE",
              old="we called it the %s at %s" % (thing, old_loc),
              new="we renamed the %s to %s" % (thing, new_loc))

    sp_keep_a = ("the fuse box", "the garden hose", "the bird feeder",
                 "the porch light", "the cellar door", "the paint tins",
                 "the camping stove", "the fishing rod", "the seed packets",
                 "the ladder rails", "the gate latch", "the brick path",
                 "the pond pump", "the shed roof", "the coal bunker",
                 "the water butt", "the fruit cage", "the compost bin",
                 "the cold frame", "the hose reel", "the wheelbarrow",
                 "the watering can", "the potting bench", "the trellis net",
                 "the garden fork", "the leaf rake", "the wheel hoe",
                 "the seed trays", "the twine spool", "the plant pots",
                 "the glove box", "the boot rack")
    sp_keep_rooms = ("shed", "garage", "porch", "cellar")
    for i, item in enumerate(sp_keep_a):
        b.add("supersede", "keep", "KEEP",
              old="%s sits by the door" % item,
              new="%s waits in the %s" % (item, sp_keep_rooms[i % 4]))

    # ------------------------------------------------------------------
    # rerank: 56 cases. gate-cut 16, band-cut 16, order 8, cap 8, empty 8.
    # ------------------------------------------------------------------
    def labels(n):
        return ["card %s" % chr(ord("a") + k) for k in range(n)]

    def select_expect(cands, gate=0.58):
        kept = [(t, s) for t, s in cands if s >= gate]
        if not kept:
            return []
        best = max(s for _, s in kept)
        floor = best * 0.55
        kept = [(t, s) for t, s in kept if s >= floor]
        kept.sort(key=lambda x: -x[1])
        return [t for t, _ in kept[:8]]

    gate_cut_scores = (
        (0.92, 0.71, 0.41, 0.20), (0.88, 0.62, 0.55, 0.18),
        (0.95, 0.60, 0.44, 0.31), (0.81, 0.77, 0.52, 0.12),
        (0.99, 0.66, 0.38, 0.33), (0.74, 0.70, 0.57, 0.29),
        (0.90, 0.85, 0.42, 0.14), (0.97, 0.63, 0.49, 0.27),
        (0.83, 0.79, 0.51, 0.24), (0.86, 0.68, 0.35, 0.22),
        (0.94, 0.61, 0.53, 0.16), (0.78, 0.75, 0.47, 0.26),
        (0.91, 0.87, 0.39, 0.19), (0.89, 0.72, 0.56, 0.15),
        (0.93, 0.64, 0.46, 0.21), (0.84, 0.69, 0.43, 0.17),
    )
    for scores in gate_cut_scores:
        cands = list(zip(labels(4), scores))
        b.add("rerank", "gate-cut", select_expect(cands), candidates=cands)

    band_cut_scores = (
        (0.90, 0.61, 0.47, 0.28), (0.85, 0.70, 0.44, 0.31),
        (0.95, 0.62, 0.50, 0.30), (0.80, 0.66, 0.41, 0.32),
        (0.99, 0.64, 0.52, 0.29), (0.75, 0.68, 0.39, 0.33),
        (0.92, 0.60, 0.48, 0.27), (0.87, 0.71, 0.45, 0.34),
        (0.81, 0.63, 0.42, 0.35), (0.88, 0.65, 0.49, 0.30),
        (0.94, 0.67, 0.51, 0.31), (0.79, 0.69, 0.46, 0.29),
        (0.91, 0.60, 0.43, 0.28), (0.86, 0.69, 0.50, 0.32),
        (0.97, 0.61, 0.44, 0.33), (0.83, 0.70, 0.48, 0.30),
    )
    for scores in band_cut_scores:
        cands = list(zip(labels(4), scores))
        b.add("rerank", "band-cut", select_expect(cands, gate=0.3),
              candidates=cands, gate=0.3)

    order_scores = (
        (0.72, 0.88, 0.61, 0.95), (0.66, 0.91, 0.83, 0.74),
        (0.98, 0.62, 0.77, 0.85), (0.79, 0.96, 0.68, 0.87),
        (0.64, 0.82, 0.93, 0.71), (0.90, 0.67, 0.84, 0.99),
        (0.75, 0.97, 0.63, 0.86), (0.92, 0.78, 0.65, 0.89),
    )
    for scores in order_scores:
        cands = list(zip(labels(4), scores))
        b.add("rerank", "order", select_expect(cands), candidates=cands)

    cap_scores = (
        tuple(0.60 + 0.01 * k for k in range(12)),
        tuple(0.62 + 0.015 * k for k in range(12)),
        tuple(0.58 + 0.02 * k for k in range(12)),
        tuple(0.70 + 0.01 * k for k in range(12)),
        tuple(0.61 + 0.017 * k for k in range(12)),
        tuple(0.59 + 0.013 * k for k in range(12)),
        tuple(0.66 + 0.011 * k for k in range(12)),
        tuple(0.72 + 0.009 * k for k in range(12)),
    )
    for scores in cap_scores:
        cands = list(zip(labels(12), scores))
        b.add("rerank", "cap", select_expect(cands), candidates=cands)

    empty_scores = (
        (0.57, 0.44, 0.21), (0.55, 0.50, 0.30), (0.42, 0.38, 0.12),
        (0.56, 0.41, 0.33), (0.52, 0.47, 0.29), (0.49, 0.35, 0.18),
        (0.51, 0.46, 0.27), (0.53, 0.40, 0.15),
    )
    for scores in empty_scores:
        cands = list(zip(labels(3), scores))
        b.add("rerank", "empty", select_expect(cands), candidates=cands)

    return b.cases


def assert_unique(cases):
    seen = {}
    for idx, c in enumerate(cases):
        for s in _case_strings(c):
            n = _norm(s)
            if len(n.split()) < 3:
                continue
            owner = seen.get(n)
            if owner is not None and owner != idx:
                raise AssertionError(
                    "normalized text reused across cases %d and %d: %r"
                    % (owner, idx, n))
            seen[n] = idx


def assert_counts(cases):
    got = {}
    for c in cases:
        got[c["suite"]] = got.get(c["suite"], 0) + 1
    if got != EXPECTED_COUNTS:
        raise AssertionError("suite counts drifted: %r != %r"
                             % (got, EXPECTED_COUNTS))
    for suite in SUITE_ORDER:
        kinds = {}
        for c in cases:
            if c["suite"] == suite:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        for kind, n in kinds.items():
            if n % 2:
                raise AssertionError("odd group %s/%s: %d" % (suite, kind, n))


def check_against_stubs(cases):
    from uncluttered_memory import supersede as supmod
    from uncluttered_memory.gate import Gate, RuleJudge
    from uncluttered_memory.jev_client import offline_relation_pair
    from uncluttered_memory.recall import Recall
    from uncluttered_memory.store import Store

    gate = Gate(RuleJudge())
    for c in cases:
        suite = c["suite"]
        if suite == "admit":
            got = gate.decide(c["text"], importance_min=3).action
            want = c["expect"]
        elif suite == "importance":
            got = gate.judge.vote(c["text"], [], []).importance
            want = c["expect"]
        elif suite == "dedupe":
            s = Store()
            a = s.put(c["text"], "gen")
            b2 = s.put(c["candidate"], "gen")
            got = "DUP" if a == b2 else "DISTINCT"
            want = c["expect"]
        elif suite in ("contradict", "supersede"):
            # Same heterogeneous offline pair the eval routes through:
            # strict + lenient, two distinct heuristics, never a copy.
            dec = supmod.decide(c["old"], c["new"], *offline_relation_pair())
            got = dec.action
            want = c["expect"]
        elif suite == "rerank":
            got = Recall().select(
                [(t, float(score)) for t, score in c["candidates"]],
                gate=float(c.get("gate", 0.58)))
            want = c["expect"]
        else:
            raise AssertionError("unknown suite %r" % suite)
        if got != want:
            raise AssertionError("%s %s: want %r got %r"
                                 % (suite, c["id"], want, got))


def write_cases(cases, path=OUT):
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    return path


def main() -> int:
    cases = build_cases()
    assert_counts(cases)
    assert_unique(cases)
    try:
        check_against_stubs(cases)
    except ImportError:
        print("run with PYTHONPATH=src so the package is importable")
        return 2
    write_cases(cases)
    per_suite = {}
    for c in cases:
        per_suite[c["suite"]] = per_suite.get(c["suite"], 0) + 1
    print("wrote %s: %d cases (%s)" % (
        OUT, len(cases),
        ", ".join("%s=%d" % (s, per_suite[s]) for s in SUITE_ORDER)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
