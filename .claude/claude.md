# Project overview

A personal capture-and-research pipeline. The user saves passages, images, and
video links throughout the day with a manual research/casual flag. A daily
batch job clusters related captures, runs resource-gathering and validation
for research-flagged clusters, and files everything into a queryable backlog
— the goal is to reduce the cost of returning to topics there wasn't time for,
not to produce a one-shot daily digest.

# Architecture at a glance

1. **Capture** — always-on lightweight endpoint. Writes raw item + manual
   research/casual flag + metadata (source URL, timestamp, content type).
2. **Daily batch job** (separate deployment from capture, not a request/response
   service):
   - Cluster/dedup pass (exact URL match + embedding similarity)
   - Branch: casual clusters file as-is; research clusters go through
     gather-resources → validate-and-organize
   - Both paths converge into the backlog store
3. **Feedback loop** — manual flag corrections and backlog revisit behavior
   feed back into the classifier's eval set. This is the highest-leverage
   eval signal in the system; don't let it go uncollected.

Full pipeline diagram and rationale: see conversation history / `/docs/architecture.md` once written — don't re-derive the design from scratch in-session, ask the user if it's missing.

# Capture client (browser extension)

- Manifest V3 only. Content script handles selection capture, the
  `commands` API provides the save hotkey, and a background service worker
  POSTs to the capture API. MV3 service workers have no persistent memory —
  reload state from `chrome.storage` on wake, never hold it in module-level
  variables.
- **Never hardcode the backend URL or API key in the extension.** Both live
  in an options page backed by `chrome.storage.sync`. This is the one
  decision that makes "works for me" and "works for someone else's backend"
  the same artifact instead of a future rebuild.
- Distribution, in order — don't skip ahead to a later stage before the
  earlier one is actually being used:
  1. Load unpacked locally (`chrome://extensions` → Developer mode) for
     day-to-day personal use.
  2. Share the zipped unpacked extension + self-host instructions with a
     few early testers. No store review needed at this stage.
  3. Chrome Web Store only once there's a real audience beyond testers.
     Requires a privacy policy (non-negotiable — this captures page
     content) and a $5 one-time developer fee. First submission from a new
     developer account can take 1-2 weeks to review; budget for that.
- If multiple people end up sharing a backend: default to each user
  supplying their own LLM API key via the options page. Don't default to a
  shared key paid for by one person — that's the same cost-control problem
  as the load-testing work, recurring at the distribution layer instead of
  the infra layer.

# Model configuration

- **Development uses Groq** via `langchain-groq` (`ChatGroq`). Requires
  `GROQ_API_KEY` in the environment. Default dev model:
  `llama-3.3-70b-versatile`; use `openai/gpt-oss-120b` for steps needing more
  reliable tool-calling (gather-resources, validate-and-organize).
- **Never hardcode a model name inline.** All model instantiation goes
  through a single `get_chat_model()` factory, switched via a
  `MODEL_PROVIDER` env var (`groq` | `anthropic` | `openai`). This keeps the
  eventual production model swap a one-line config change, not a refactor.
- **Groq JSON gotcha**: structured outputs (classifier verdicts, judge
  scores) can arrive wrapped in markdown fences even when told not to.
  Always parse through a shared `extract_json()` helper — never call
  `json.loads()` directly on raw model output.
- Not every Groq-hosted model has equally reliable tool-calling. Verify
  before swapping the dev model for anything used in the gather/validate
  steps specifically.

# Evaluation conventions

- Every agent judgment point (research/casual classification, resource
  relevance, groundedness of organized output) gets an LLM-as-judge backed by
  a hand-labeled calibration set — judges get calibrated against known-good
  and known-bad examples before being trusted, not assumed correct.
- Score precision *and* recall on classification tasks, not just accuracy —
  classes are not balanced (casual saves vastly outnumber research bursts).
- Structural correctness (schema conformance) is checked deterministically,
  never via LLM judge. A schema failure is a code bug, not a quality dip —
  alert on it accordingly.
- Real disagreements (manual overrides, corrected clusters) get added to the
  relevant eval set as new cases — don't let the eval set go stale relative
  to real usage.

# Monitoring conventions

- All agent runs are traced via Langfuse; judge scores attach to the trace
  they evaluate, not logged separately.
- Job-level monitoring (did the daily batch run at all, did it process every
  pending item) is tracked separately from item-level monitoring (per-item
  judge scores). A clean item-level dashboard can hide a batch job that
  silently stopped running.

# Commands

- `uvicorn app.main:app --reload` — run the capture API locally
- `python -m batch.run_daily` — run the batch job manually, outside the schedule
- `pytest evals/` — run the eval suite, including judge calibration cases
- `locust -f loadtest/locustfile.py --host=<url>` — load test (see deployment
  notes for the mocked-agent mode used to keep load tests cheap)
- `chrome://extensions` → Developer mode → Load unpacked → select
  `extension/` — reload here after any extension change; service workers
  don't hot-reload