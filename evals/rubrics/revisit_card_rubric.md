# Revisit Card eval rubric

Used by `evals/run_revisit_card_eval.py` — both as the basis for the
deterministic checks it runs automatically, and as the prompt given to the
LLM judge when `OPENAI_API_KEY` is set. A human reviewer should be able to
apply the same rubric by hand to spot-check the judge's scores.

Each generated card (`title`, `why_saved`, `original_context`,
`next_action`) is scored against the **capture(s) or cluster it was
generated from** — never against some external notion of "is this a good
fact," since the model is only supposed to work from what was provided.

## Scored dimensions (1-5 each)

**intent_preservation** — does the card preserve *why the user saved this*?
- 1: contradicts or ignores the capture's `label` (e.g. treats a casual
  save as urgent, or vice versa)
- 3: technically consistent with the label but generic/boilerplate
- 5: clearly reflects the specific reason this particular capture/cluster
  was worth keeping

**context_grounding** — does it stay grounded in the provided context?
- 1: states specifics (names, numbers, claims, sources) that don't appear
  anywhere in the input
- 3: stays accurate but is vague where it could have used available detail
- 5: uses the specific available details, and if context was thin, says so
  explicitly rather than papering over the gap

**usefulness** — would this actually help the user resume the topic later,
days or weeks from now, with no other memory of the original moment?
- 1: too vague to reconstruct what this was about
- 3: would help a little, but the user would still need to reread the
  original capture
- 5: gives enough to re-enter the train of thought without rereading
  everything

**next_action_quality** — is `next_action` specific and actually doable?
- 1: missing, or so generic it could apply to literally any capture
- 3: plausible but generic given how much context was actually available
- 5: a single concrete, specific action that follows from the content

**conciseness** — is it clear without being bloated?
- 1: rambling, redundant, or padded with filler
- 3: a bit wordy but not actively unclear
- 5: says exactly what's needed and stops

## Binary flags

These are pass/fail signals, not gradients — any one of them being `true`
should be treated as a quality problem regardless of the 1-5 scores.

- **invented_fact** — the card states a name, number, source, or claim that
  isn't present in the input context. This is the most important flag:
  inventing detail is worse than being vague.
- **missing_next_action** — `next_action` is empty, null, or not present.
- **too_generic** — the card (usually `next_action`) is boilerplate that
  doesn't reflect anything specific about this capture/cluster, in a case
  where the available context was rich enough to support something more
  specific. (Boilerplate is *expected and fine* for genuinely thin-context
  cases — see `allow_generic_next_action` in the dataset. Flagging this is
  only meaningful when context was actually available to do better.)
- **empty_or_invalid** — one of the 4 required fields is missing, empty,
  or not a string at all (structural failure, not a quality judgment).

## Notes on automated scoring

`run_revisit_card_eval.py` computes `invented_fact`, `missing_next_action`,
`too_generic`, and `empty_or_invalid` deterministically wherever it
reasonably can (required-field presence, a per-case `forbidden_terms` list,
and exact-match against the known rule-based boilerplate strings). These
are heuristics, not ground truth — see the README's "limitations of
LLM-as-judge" section for what this does and doesn't catch.

The 1-5 dimension scores are **not** computed deterministically; they only
come from the optional LLM judge. Treat them as a rough signal to spot
trends across reruns/prompt versions, not as a precise quality metric.
