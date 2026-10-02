# Playground (P4): sample conversation, recorded 2026-10-02

`python3 playground/demo.py` admits six chat lines through the real
Store/Gate with the offline RuleJudge stub (not Jev), prints each
gate verdict, then shows recall, inject, and the quarantine queue.
Transcript below is the actual output of that command, committed as
the record; re-running it must print the same verdicts.

## What it shows

- Two STORE lines: a routine durable fact (`standup 9am daily`) and
  a vital one (visa interview with a date and office).
- Two DROP lines for different reasons: filler (`ok`, trivial) and
  play (`lol ...`, junk rule), plus a sensitive DROP (phone number:
  privacy outranks review, so it drops instead of quarantining).
- One QUARANTINE line: vague chatter the stub cannot read fails
  closed to the quarantine queue, visible in REVIEW, never stored.
- Recall finds the stored fact by surface wording; inject packs it
  into a context string within budget.

## Transcript

```
UnclutteredMemory playground (offline RuleJudge stub, not Jev)
IN   'standup 9am daily'
GATE action=STORE reasons=durable+important
STORE action=STORE
IN   'My visa interview is on Monday at the downtown office'
GATE action=STORE reasons=durable+important
STORE action=STORE
IN   'ok'
GATE action=DROP reasons=not-durable-or-trivial
STORE action=DROP
IN   'lol that meeting was hilarious lol'
GATE action=DROP reasons=play>0.7
STORE action=DROP
IN   'The weather was nice yesterday in some vague way'
GATE action=QUARANTINE reasons=uncertain-low-conf
STORE action=QUARANTINE
IN   'My phone number is 555-1234, call me anytime'
GATE action=DROP reasons=sensitive>0.7
STORE action=DROP
RECALL query='standup daily' texts=['standup 9am daily']
INJECT context='standup 9am daily'
REVIEW quarantined=1
Q qid=1 reason=uncertain-low-conf text='The weather was nice yesterday in some vague way'
STATUS live=2 quarantined=1 error_count=0
```

## Limits of this demo

The stub reads surface features, not meaning: reworded paraphrases
of the stored facts may miss on recall (see the paraphrase limit in
the README), and the stub is never labeled as Jev. Live Jev agrees
with the frozen golden labels 41.7% of the time on the free tier
(see `docs/label-audit-20261002.md`); this demo makes no live calls.
