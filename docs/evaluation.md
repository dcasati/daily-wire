# Evaluation

`daily-wire eval` (also `pytest`, and run in CI and before every publish) runs the pipeline on `tests/fixtures` (synthetic: invented events, ground truth in `eval.yaml`) and applies thresholds from `evaluate.THRESHOLDS`.

| Metric | Definition | Threshold | Last result |
|---|---|---|---|
| Precision | selected events matching a ground-truth significant event / selected | ≥ 0.90 | 1.00 |
| Recall | truth events selected / truth events | ≥ 0.80 | 1.00 |
| Duplicate event rate | selected events mapping to an already-selected truth event | 0 | 0 |
| Claim support | statements with zero grounding errors vs cited evidence | ≥ 0.95 | 1.00 |
| Citation validity | every cited URL was collected; refs resolve; numbering gapless | 1.0 | 1.0 |
| Incorrect attribution | statements citing sources outside their own event | 0 | 0 |
| Unchanged repeats | statements for unchanged events on rerun; non-updated events after an update | 0 | 0 |
| Word compliance | editorial words ≤ 600 | 1.0 | 1.0 (161 words in sample) |
| Adversarial rejection | 10 hostile writer outputs rejected (fabricated/misattributed citation, invented number/name, unhedged weak claim, injection, unknown event/URL, unsupported assertion, overlong) | 1.0 | 1.0 |
| Pipeline reliability | publishes despite one failing source | 1.0 | 1.0 |
| EPUB validity | structural validator (`publish.validate_epub`) | 1.0 | 1.0 |
| Cost / edition | estimated USD for the stub-LLM run | ≤ 0.05 | $0.0004 (estimated tokens) |
| Injection leaks | quarantined text present in output | 0 | 0 |
| Budget hard stop | `max_daily_usd=0` makes no call | true | true |

## Limits (important)
- The fixture set is small and synthetic; scores near 1.0 show the mechanics work, **not** real-world editorial quality. Build a larger historical fixture set (saved real feeds + human-labelled significant events) before trusting precision/recall figures.
- The grounding check is lexical. It does not prove a claim is *true* (sources can be wrong) nor catch every distortion made from correct words.
- Incorrect attribution is measured as citation-to-event mismatch, not "who said what" inside a sentence.
- EPUB validation is a structural checker, **not** W3C `epubcheck`. Run `epubcheck briefing-*.epub` (Java) before relying on strict validity; it was not run here (no network/Java in the build sandbox).
- No LLM judge is used anywhere. Human spot checks of live editions are recommended for the first weeks.
