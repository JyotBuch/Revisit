---
description: Scaffold a minimal end-to-end version of the capture-and-research pipeline
argument-hint: [capture-only|full]
---

Build a basic, scratch version of the system described in CLAUDE.md. Scope:
$ARGUMENTS (default to "full" if no argument is given).

Goal: a thin vertical slice that actually runs end to end, not a polished
implementation. Every stage should be real, executable code — if a stage's
internal logic is intentionally minimal, stub it with a clear `# TODO:` and a
one-line comment on what it's standing in for. Never skip or delete a stage
to make the slice easier; a missing stage hides exactly the integration bugs
this scratch build is meant to surface.

Build in this order:

1. **Capture API** (FastAPI) — one POST endpoint writing
   `{content, source_url, timestamp, content_type, flag}` to a local SQLite
   file. No auth yet.
2. **Batch job script**, run manually for now (no scheduler):
   a. Pull all unprocessed captures.
   b. Cluster pass — exact URL match only; leave a `# TODO:` where embedding
      similarity will go later.
   c. Branch on the flag: casual clusters write straight to the backlog
      table. Research clusters call a `gather_resources()` stub that returns
      a hardcoded placeholder result — no real tool-calling yet.
   d. `validate_and_organize()` stub that runs the placeholder through a
      real JSON schema check. Build the actual schema now even though the
      content behind it is fake.
   e. Write to the backlog table.
3. **Model factory** (`get_chat_model()`), wired to Groq per CLAUDE.md, even
   if this scratch version doesn't call the model yet anywhere. Get the
   abstraction in place before anything comes to depend on a specific model.
4. **One eval test**, via `pytest` — a single hand-written case asserting
   the schema check passes and the casual/research branch routes correctly.
   Don't build the LLM-judge yet; it needs real model output to calibrate
   against, which this scratch build doesn't produce.
5. Append (don't replace) a short README section listing exactly what's
   real versus stubbed, so nothing fake gets mistaken for working later.

If `$ARGUMENTS` is `capture-only`, stop after step 1 and report that the
batch job, model factory, and eval were intentionally skipped.

After building, run one casual capture and one research capture through the
full path and report what actually executed versus what's still a stub.