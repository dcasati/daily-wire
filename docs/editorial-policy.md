# Editorial policy → enforcement

| # | Principle | Enforced by (test) |
|---|-----------|--------------------|
| 1 | Facts first: observed / attributed / assessment | writer schema `kind`; low-confidence or contested claims must be `attributed` with attribution wording (`verify.py`; `unhedged_weak_claim`) |
| 2 | Significance over popularity | score parts + impact-term requirement (`rank.shortlist`); chef/budget noise excluded (`test_noise_excluded…`) |
| 3 | No advocacy/sensationalism | system prompt; assertive verbs must be in cited evidence (`unsupported_assertion`). Tone beyond this is **not** automatically checkable |
| 4 | Corroborate | `independent_origins`, confidence tiers |
| 5 | Never invent events/quotes/dates/URLs | numbers, names, URLs, citations checked against evidence (`invented_number`, `invented_name`, `unknown_url`, `fabricated_citation`) |
| 6 | Only retrieved evidence | writer sees only packets; `unknown_event` rejected |
| 7 | Event time ≠ publication time | `event_time` kept separate (null unless stated); texts rely on publication time; gaps note it |
| 8 | No repeats unless changed | `changes.annotate` (unchanged dropped; `test_rerun_repeats_nothing…`) |
| 9 | No filler sections | empty sections not rendered; reduced edition when little qualifies |
| 10 | Shorter when quiet | rerun test publishes a short "No developments" edition |
| 11 | Flag uncertainty | disagreements/gaps in packets; contested figures must be disclosed (`test_contradictory_reports_disclosed`) |
| 12 | Syndication ≠ corroboration | shared `origin` (`test_syndicated_*`) |
| 13 | Feeds are untrusted data | injection quarantine, `<evidence>` isolation, HTML escaping (`test_collect_partial_failure_and_quarantine`, `test_epub_escapes_untrusted_text`) |
| 14 | No model knowledge as evidence | grounding check against cited evidence |

Wire detection is heuristic (credit lines such as "(Reuters)"); uncredited syndication may be counted as independent.
