# Jev response fixtures

Recorded from live calls to the native Jev endpoint
(`https://opencode.ai/zen/v1/systemone`, model `jev-1.13-free`,
2026-10-02). Bodies are raw HTTP response text, replayed through the
real client parser in tests with the network stubbed out.

- `jev_gate_stop_loss_recorded.json`: writer-gate batch for the text
  "My stop-loss is 8%". dur 0.69, importance choice s4, sens 0.22,
  stop s1.
- `jev_gate_play_recorded.json`: writer-gate batch for the text
  "Buy the whole exchange lol". dur 0.2, importance choice s0 (the
  trivial level that exposed the old off-by-one parse), stop s1.
- `jev_relation_recorded.json`: relation question on an office
  address update; choice supersede.

Derived failure fixtures (hand-built from the recorded shape, not
live captures):

- `jev_gate_out_of_range.json`: durable noul outside [0, 1].
- `jev_gate_missing_answers.json`: reply without an answers object.
- `jev_gate_missing_choice.json`: importance answer without a choice.
- `jev_gate_probability_alias.json`: durable score sent under the
  `probability` alias.
- `jev_score_level.json`: score-type answer carrying a `level`
  (hand-built from the documented answer shape; no live capture yet,
  the writer gate asks choice questions for importance).
