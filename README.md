# Revisit

A personal capture-and-research pipeline. Save things you encounter online —
articles, passages, videos, images, notes — and mark each as `casual` or
`return`. Captures can be turned into Revisit Cards that help you pick your
train of thought back up.

## What is a Capture?

A **Capture** is the raw unit saved by the user: a link, a selected passage,
an image, a video, or a free-form note, tagged with a `label` (`casual` or
`return`) describing whether it's worth coming back to. Each capture has:

- `id` — server-generated identifier
- `source_type` — `article` | `passage` | `video` | `image` | `note`
- `url`, `title`, `selected_text`, `user_note` — optional; at least one of
  `url`, `selected_text`, or `user_note` must be present
- `label` — `casual` | `return`
- `status` — `saved` | `extracted` | `failed` (lifecycle, set by later
  processing stages — every capture starts as `saved`)
- `extracted_text` — set by the extraction step (see below); `null` until
  extraction runs
- `extraction_error` — set if extraction fails; `null` otherwise
- `created_at` / `updated_at`

## What does extraction mean?

**Extraction** turns a capture's raw saved fields into a single
`extracted_text` value worth feeding into later processing (Revisit Cards,
eventually search/retrieval). It's triggered manually per-capture via
`POST /captures/{capture_id}/extract` — there's no background worker yet.
Rules by `source_type`:

- `passage` → `selected_text`
- `note` → `user_note`
- `article` → fetches `url` and pulls the page's visible text via
  `requests` + BeautifulSoup
- `video` / `image` → uses `selected_text` or `user_note` if present;
  otherwise marks the capture `failed` with a "not implemented yet" message,
  since transcript/OCR extraction isn't built

On success, `status` becomes `extracted` and `extracted_text` is set. On
failure, `status` becomes `failed` and `extraction_error` explains why.

**Article extraction is intentionally basic for now**: a raw GET request and
`get_text()` over the whole page, no readability heuristics, no boilerplate
stripping beyond removing `<script>`/`<style>` tags, no JS-rendered content
support, and no retries. It's enough to validate the capture → extract loop
end-to-end; a real readability/extraction library is a likely upgrade once
this proves useful, not before.

## What are embeddings, and why before clustering?

An **embedding** is a fixed-length vector representation of a capture's
`extracted_text`, generated via `POST /captures/{capture_id}/extract` first
and stored via `POST /captures/{capture_id}/embed`. Captures whose text is
similar in meaning end up with vectors that are close together (measured
here via cosine similarity), which is what makes
`GET /captures/{capture_id}/similar` possible.

This is a prerequisite for clustering, not clustering itself: clustering
needs a notion of "distance" between captures to group them, and embeddings
are what supply that distance. Building per-capture similarity search first
means the distance metric can be validated on its own — one capture at a
time — before trusting it to drive automatic grouping.

Embeddings are stored in a separate `capture_embeddings` table (one row per
capture, via pgvector's `vector` column type), not as a column on
`captures`, so the embedding model/dimension can change independently of the
capture schema.

**Provider configuration**: set `OPENAI_API_KEY` in your environment (or
`.env`) to use real OpenAI embeddings (`text-embedding-3-small`). If it's
unset, embeddings fall back to a **deterministic local fake embedding** —
clearly intended for development/testing only. The fake embedding hashes the
input text into a fixed seed and generates pseudo-random vector
coordinates from that seed; it has no notion of semantic meaning, so
similarity scores from it are not meaningful — they only happen to be
identical for identical text. Don't use it to judge real similarity quality.
Each stored embedding records which `embedding_model` produced it, so you
can tell fake from real after the fact.

## What does clustering mean in REVISIT, and why after embeddings?

**Clustering** groups embedded captures that are about the same thing, so
related saves can eventually surface together (e.g. in a future Revisit Card
covering a whole topic, not just one capture). It's triggered manually via
`POST /clusters/run` — there's no background job yet.

Clustering depends on embeddings existing first because it needs a distance
metric between captures, and embeddings are what supply that metric (see
the embeddings section above). Only captures that have *both* extraction
and an embedding are considered; everything else is silently skipped.

**Algorithm — greedy, single pass, intentionally basic:**

1. Pull every capture that has an embedding, ordered by `created_at`.
2. For each capture, compare it (cosine similarity) against the
   *representative* of every existing cluster — the representative is
   simply whichever capture started that cluster.
3. If the best match is `>= similarity_threshold`, join that cluster; the
   `similarity_score` against the representative is recorded on the
   `cluster_items` row.
4. Otherwise, start a new cluster with this capture as its representative
   (`similarity_score` is `null` for representatives — they weren't matched
   against anything).
5. A new cluster's `title` is the representative capture's `title`, or
   `"Untitled Cluster"` if it has none — a placeholder until LLM-generated
   titles/summaries exist.

This is a single linear pass, not k-means/HDBSCAN/anything iterative — it's
order-dependent and the "representative" is arbitrary (just "whoever got
there first"), which is a known limitation of basic greedy clustering. It's
enough to validate the embed → group → inspect loop end-to-end; a real
clustering algorithm (and LLM-generated cluster titles/summaries) is a
likely upgrade once this proves useful, not before.

**Why the threshold defaults to 0.60**: manual testing of the embeddings
milestone (real OpenAI embeddings) found genuinely related captures scoring
around **0.66** cosine similarity, and unrelated ones around **0.05**. 0.60
sits just below the observed "related" cluster and well above the observed
"unrelated" floor, so it's a deliberately conservative starting point based
on that data — not a guess, and not hardcoded into the clustering logic.
Pass `?similarity_threshold=` to `POST /clusters/run` to override it per
run.

**Idempotency**: `POST /clusters/run` clears *all* existing
`clusters`/`cluster_items` rows and rebuilds them from scratch from the
current set of embedded captures, every time it's called. This was chosen
over incrementally patching existing clusters because representatives have
no stable identity across runs (a cluster's representative is just
whichever capture happened to be processed first) — reconciling old
assignments against a fresh pass would need extra bookkeeping for little
benefit at this stage. The tradeoff: cluster `id`s are not stable across
reruns, so don't treat a cluster's id as a long-lived identifier yet. A
capture can belong to at most one cluster at a time (`capture_id` is unique
on `cluster_items`), enforced at the database level.

## What is a Revisit Card?

A **Revisit Card** is the generated output that helps you pick something
back up later. There are now two kinds, both stored in the same
`revisit_cards` table, distinguished by `card_type`:

- **Individual** (`card_type: "individual"`) — generated from one capture.
  `capture_id` is set, `cluster_id` is `null`.
  - `title` — the capture's title, or `"Untitled Revisit Card"` if it has
    none
  - `why_saved` — why it's worth revisiting, based on the capture's `label`
  - `original_context` — `user_note`, falling back to `selected_text`,
    falling back to `url`
  - `next_action` — a suggested follow-up, based on the capture's
    `source_type`

- **Cluster** (`card_type: "cluster"`) — generated from a whole cluster of
  related captures. `cluster_id` is set, `capture_id` is `null`.
  - `title` — the cluster's `title`, falling back to the first capture's
    `title`, falling back to `"Untitled Revisit Card"`
  - `why_saved` — `"You saved multiple related captures as worth returning
    to."` if any capture in the cluster is labeled `return`, otherwise
    `"...casually."`
  - `original_context` — up to 3 snippets (one per capture, each capped at
    200 characters), preferring `user_note` → `selected_text` →
    `extracted_text` → `url` per capture, joined as a readable bulleted list
  - `next_action` — specific to the shared `source_type` if every capture in
    the cluster has the same one (e.g. all `note`), otherwise a generic
    "review the grouped captures" prompt

A database **check constraint** (`ck_revisit_cards_exactly_one_owner`)
enforces that exactly one of `capture_id`/`cluster_id` is set on every row —
this isn't just an application-level convention, Postgres rejects inserts
that violate it.

## How is content generated: rule-based vs. LLM?

Every Revisit Card also records how it was produced:

- `generation_method` — `"rule_based"` | `"llm"`
- `model_name` — which chat model produced it (`null` for rule-based cards)
- `prompt_version` — which prompt version produced it (`null` for
  rule-based cards), so prompt changes are traceable on already-generated
  cards

**Rule-based generation is the default and the fallback** — both
`POST /captures/{capture_id}/revisit-card` and
`POST /clusters/{cluster_id}/revisit-card` default to
`generation_method=rule_based` if you don't pass the query parameter at
all, and *always* fall back to it if you ask for `llm` but it's
unavailable:

- `OPENAI_API_KEY` isn't set
- the OpenAI API call itself fails (network error, invalid model name, rate
  limit, etc.)
- the model's response isn't valid JSON, or is missing/empty on any of the
  4 required fields, or `next_action` is too long to be "concise"

In all of those cases the card is still created — just with
`generation_method: "rule_based"` instead of erroring out. This is
deliberate: requesting `llm` should never be able to break card creation,
only opt into a (currently unverified-by-evals) richer generation path.

**LLM generation** (`app/services/llm.py`) calls an OpenAI chat model with
the same underlying context the rule-based path would use (capture
fields, or up to 5 captures' fields for a cluster), and asks it to return
*only* `title`, `why_saved`, `original_context`, and `next_action` as JSON.
The prompt explicitly instructs the model not to invent URLs, sources, or
facts beyond what's provided, and to say so plainly in `original_context`
rather than guess if the given context is thin. The response is validated
(all 4 fields present, non-empty strings, `next_action` under 300
characters) before it's trusted — anything else is treated as a failure
and triggers the rule-based fallback above.

**Configuration**:

- `OPENAI_API_KEY` — same variable used for embeddings (see above). Without
  it, `generation_method=llm` is accepted but always resolves to
  `rule_based`.
- `OPENAI_REVISIT_CARD_MODEL` — optional, defaults to `gpt-4o-mini` if
  unset. Lets you pick a different chat model without a code change.

**Cluster-level cards are the more important product behavior long-term**:
the whole point of clustering is to let the user revisit a *topic*, not
re-discover the same idea capture-by-capture. Individual cards stay useful
for captures that never get grouped (or before clustering has run), but
cluster cards are the shape this is actually building toward — combining
context across captures into one place to resume from.

Cards are generated on demand via the API below, not by a background job.

**Cluster id stability**: because clustering uses clear-and-rebuild (see
above), a cluster's `id` does not survive a clustering rerun. A cluster
Revisit Card's `cluster_id` therefore points at a cluster that may no longer
exist after the next `POST /clusters/run` — the card itself is unaffected
(it already captured a snapshot of the context at creation time), but you
can no longer use that `cluster_id` to look up "the current state of this
cluster" after rerunning. Solving stable cluster identity is out of scope
for this milestone and is a real open problem for the next one.

## Evaluating Revisit Card quality offline

`evals/run_revisit_card_eval.py` is a repeatable, offline comparison of
rule-based vs. LLM-generated cards against a fixed dataset
(`evals/datasets/revisit_card_eval.jsonl`) — it exists to answer "is the
LLM path actually better, and where does each approach fail?" with
evidence instead of impression, before `llm` is trusted as a default
anywhere.

It deliberately **reuses the exact same rule-based builder functions and
LLM call/validation code that the live API uses** (imported directly from
`app/services/revisit_card_store.py` and `app/services/llm.py`) rather than
reimplementing the logic — so the eval can never drift from what the
running app actually does.

**Run it:**

```bash
python -m evals.run_revisit_card_eval
```

Run from the project root with the venv active. Without `OPENAI_API_KEY`
set, only the rule-based path is evaluated (the LLM path is skipped
entirely — mirroring how the live API behaves when `generation_method=llm`
is requested without a key).

**What it measures**, per case in the dataset, for each generation method
attempted:

- **Deterministic checks** (always run): required fields present and
  non-empty, `next_action` non-empty and not over-length, a per-case
  `forbidden_terms` list not appearing anywhere in the card (a cheap proxy
  for "didn't invent specifics"), and exact-match against the known
  rule-based boilerplate strings (to flag `too_generic` only when the input
  context was rich enough that boilerplate represents a real shortfall —
  see `allow_generic_next_action` per case).
- **Optional LLM-as-judge scores** (only when `OPENAI_API_KEY` is set):
  1-5 ratings on `intent_preservation`, `context_grounding`, `usefulness`,
  `next_action_quality`, `conciseness`, plus the same 4 binary flags judged
  qualitatively instead of by string-matching. See
  `evals/rubrics/revisit_card_rubric.md` for the full rubric definitions.

**Output**: a timestamped JSON report in `evals/reports/` containing every
case's generated card, deterministic check results, judge scores (if run),
and an overall summary; plus a terminal summary (case count, rule-based and
LLM pass rates, and counts of `invented_fact` / `missing_next_action` /
`too_generic` across all generated cards).

**Limitations of the LLM-as-judge, to keep in mind when reading scores**:

- The judge currently uses the **same model** as card generation
  (`OPENAI_REVISIT_CARD_MODEL`, or `gpt-4o-mini` by default). A model
  judging its own output is a known bias risk — in one real run, the judge
  gave a rule-based card a `too_generic: false` even though it matched a
  known canned boilerplate string verbatim, which the deterministic check
  caught and the judge didn't. Don't treat judge scores as ground truth;
  treat disagreement between the judge and the deterministic checks as a
  signal worth a human look, not as the deterministic check being wrong.
- It's not validated against human-labeled cases yet — there's no
  calibration set proving the judge's 1-5 scores track human-perceived
  quality. That calibration work is a real next step before leaning on
  judge scores for anything beyond rough trend-spotting.
- `forbidden_terms` is a per-case allowlist of phrases an eval author
  predicted might appear if the model invented detail — it's a heuristic
  that catches obvious cases, not a general invented-fact detector. A model
  could invent a plausible-sounding detail using none of the listed terms
  and the deterministic check would miss it; the judge's `invented_fact`
  flag is meant to catch that gap, but it inherits the self-judging bias
  above.

This is intentionally lightweight — a first repeatable eval loop, not a
production eval platform. There's no calibration set, no per-prompt-version
regression tracking across runs, and no automatic gating of deploys on
eval results yet.

## Revisit Card feedback

The offline eval harness above answers "is this card good, in principle?"
against a fixed dataset. **Feedback answers a different question: was this
specific card actually useful to the actual user, in actual use?** Those
are not the same thing — a card can score well on the rubric and still not
get opened, or score generically and still get marked useful because the
underlying capture was simple. Without feedback, `generation_method=llm` vs
`rule_based` stays a debate settled by eval scores and vibes; with it, it
becomes a debate settled by `useful_rate` on real cards.

Each feedback event records one user reaction to one card:

- `action` — `opened` | `useful` | `not_useful` | `dismissed` |
  `next_action_taken`
- `rating` — optional, 1-5 (enforced both by the API and by a database
  check constraint)
- `comment` — optional free text
- `created_at`

A card can have many feedback events (e.g. `opened` then later `useful`) —
this is an event log, not a single mutable "rating" field on the card, so
the full interaction history is preserved.

**This is the connective tissue between offline evals and a real online
quality signal**: the eval harness can tell you a card *should* be good;
feedback tells you whether it actually was. Once enough feedback
accumulates, the natural next step (not built yet) is folding real
`useful`/`not_useful` outcomes back into the eval dataset as new cases —
the same "real disagreements become eval cases" idea used elsewhere in this
project, just applied to card quality instead of capture classification.

**API:**

```bash
# mark a card as opened
curl -X POST http://127.0.0.1:8000/revisit-cards/<card_id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"action": "opened"}'

# mark useful, with a rating and comment
curl -X POST http://127.0.0.1:8000/revisit-cards/<card_id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"action": "useful", "rating": 5, "comment": "exactly what I needed to pick this back up"}'

# mark not useful
curl -X POST http://127.0.0.1:8000/revisit-cards/<card_id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"action": "not_useful", "comment": "too generic"}'

# list feedback for one card
curl http://127.0.0.1:8000/revisit-cards/<card_id>/feedback

# aggregate counts across all cards
curl http://127.0.0.1:8000/feedback/summary
```

`GET /feedback/summary` returns total events, counts by action, the average
rating (across events that included one), `useful_rate` (`useful / (useful
+ not_useful)`, `null` if neither has happened yet), and `dismiss_rate`
(`dismissed / total`, `null` if there are no events yet at all).

## Observability

`GET /metrics/observability` is a single read-only endpoint that summarizes
the whole system's health from the database in one call, so you don't have
to run six separate manual queries to answer "is anything stuck?" or "is
the LLM path actually being used?"

It deliberately separates three different kinds of question, because
mixing them together hides what's actually wrong:

- **Pipeline health** (`pipeline`) — is data *flowing*? How many captures
  exist, broken down by `status` and `source_type`; how many have been
  extracted vs. failed extraction; how many have embeddings; cluster
  counts, including `singleton_clusters` and `average_cluster_size` (a
  cluster count alone doesn't tell you if clustering is actually grouping
  anything, or just creating one cluster per capture).
- **Product usage** (`revisit_cards`, `feedback`) — are people actually
  generating and reacting to cards? Counts by card type and generation
  method, plus the same `useful_rate`/`dismiss_rate`/average-rating
  numbers from the feedback summary above, plus `next_action_taken_rate`
  (the strongest behavioral signal of the three — it means the user didn't
  just read the card, they acted on it).
- **Eval health** (`eval`) — is there even a recent offline eval to trust?
  Surfaces the latest report's path, timestamp, and rule-based/LLM pass
  rates by reading the most recently modified file in `evals/reports/` —
  this is reading the filesystem, not the database, so it reflects when
  someone last ran `python -m evals.run_revisit_card_eval`, independent of
  what's currently in the database.

**Nulls, not misleading zeros**: anywhere a rate has an empty denominator
(no clusters yet, no ratings yet, no feedback yet, no eval report on disk
yet), the field is `null`, not `0` or `0.0`. A `useful_rate` of `0` would
claim "definitely not useful so far"; `null` correctly says "no signal
yet" — these mean very different things and conflating them would be
actively misleading once this gets read by a future dashboard.

```bash
curl http://127.0.0.1:8000/metrics/observability
```

**How this differs from real production monitoring**: this is a
synchronous, on-demand SQL aggregation endpoint — there's no time-series
storage, no alerting, no dashboards, no scraping/push interval, and no
historical trend (every call recomputes from current state; nothing here
remembers what the numbers looked like yesterday). It's a deliberately
simple "what does the system look like right now" snapshot, useful for
manual checks during development — not a replacement for Prometheus,
Grafana, or any real monitoring stack, which would be the right next step
once there's an actual production deployment to monitor.

## Daily batch processing

Every pipeline step so far — extract, embed, cluster, generate a card — is
a separate manual API call. `POST /jobs/daily-batch` runs all of them
**end-to-end for return-worthy captures in one request**:

1. Select captures where `label = "return"` (casual captures are never
   touched by the batch — not extracted, not embedded, not clustered, not
   carried into cluster cards).
2. For each selected capture: if it's still `saved`, extract it; if it now
   has `extracted_text` and no embedding yet, embed it. (Captures already
   `extracted` or already `failed` from before are left alone, not
   reprocessed — the batch only acts on what actually needs doing.)
3. Run clustering once, over whatever's now embedded.
4. Create one cluster-level Revisit Card per resulting cluster, using
   `generation_method` (defaults to `rule_based`; `llm` falls back to
   `rule_based` automatically, using the exact same fallback logic as the
   individual card-creation endpoints — a batch run can't fail just
   because the LLM call did).
5. Record the whole run as a row in `jobs`: `status` (`running` →
   `succeeded`/`failed`), `started_at`/`completed_at`, and a `summary_json`
   with counts for every step above. If anything unexpected goes wrong
   partway through, the job is marked `failed` with the error message
   stored — you can always `GET /jobs/{job_id}` afterward to see exactly
   what happened, even for a failed run.

**Why synchronous, and why this is explicitly a skeleton, not the final
design**: this whole pipeline runs inside one HTTP request/response cycle.
There is no Celery, no Redis, no cron, no worker process, and no
scheduler — calling the endpoint *is* the schedule, for now. That's a
deliberate simplification to get the end-to-end logic right and testable
first, not a belief that this is how it should run in production: a real
"daily" batch needs an actual scheduler triggering it once a day
unattended, on a worker process that can outlive a single HTTP request
(this pipeline will take longer than an HTTP timeout once there are
thousands of captures, not dozens). The eventual migration path is to move
`run_daily_batch()`'s logic as-is into a scheduled worker task — the
function doesn't need to change, just who calls it and how often.

One real consequence of "synchronous and not atomic" worth knowing: each
step (extraction, embedding, clustering, card creation) commits to the
database as it completes, the same way every other endpoint in this app
does. A failure partway through a batch run leaves earlier steps' work
committed — it does not roll back the whole run. Rerunning the batch
afterward picks up wherever it left off (already-extracted captures aren't
re-extracted, already-embedded captures aren't re-embedded), so a partial
failure is recoverable by just running it again, not by manual cleanup.

```bash
# run the batch (rule-based cluster cards, the default)
curl -X POST "http://127.0.0.1:8000/jobs/daily-batch"

# run it requesting LLM-generated cluster cards instead
curl -X POST "http://127.0.0.1:8000/jobs/daily-batch?generation_method=llm"

# list all job runs
curl http://127.0.0.1:8000/jobs

# inspect one job run, including its summary or error
curl http://127.0.0.1:8000/jobs/<job_id>
```

`GET /metrics/observability` also now reports `jobs`: `total_jobs`,
`jobs_by_status`, and the most recent `daily_batch` run's status and
timestamps — so "did the batch even run today, and did it succeed" is one
call away rather than a manual query.

## Related-resource retrieval for clusters

A cluster groups related captures, but it's still just the user's own
saved material — `POST /clusters/{cluster_id}/resources` adds **outside**
material related to the cluster's topic: search-result-style candidates
(`url`/`title`/`snippet`), validated and stored separately from the
cluster itself.

**Pipeline**: `generate_cluster_search_query(cluster)` turns a cluster
into a short query (the cluster's own `title`, falling back to the first
capture's title/text if the cluster has none) →
`retrieve_resources_for_cluster` asks a provider for candidates →
`validate_resource_for_cluster` scores each candidate → only candidates
clearing the validation threshold (default `0.50`) are stored.

**Fake provider vs. real provider**: set `SEARCH_PROVIDER=brave` and
`SEARCH_API_KEY=<key>` to use the real Brave Search API. Without both set,
retrieval falls back to a **deterministic local fake provider** — clearly
development/testing only. The fake provider does not search the web: it
builds plausible-looking candidates out of the cluster's *own* capture
text (so they have genuine vocabulary overlap with the cluster to validate
against), with fabricated `https://example-dev-resource.local/...` URLs
that don't resolve to anything real. Same as the fake embedding/LLM
fallbacks elsewhere in this project, real and fake candidates are run
through the *exact same* validation step — the fake provider doesn't get
special treatment, it's a drop-in stand-in for "a provider returned some
candidates."

**Why validation is deterministic first, not LLM-judged**: same reasoning
as extraction and clustering's first passes — a cheap, inspectable,
explainable check (lexical overlap between the cluster's aggregated
capture text and the candidate's title/snippet/query, via Jaccard
similarity) lets the retrieve → validate → store loop get built and
exercised end-to-end before adding a more expensive/judgment-based layer.
Every accepted or rejected resource records *why* in `validation_reason` —
e.g. `"rejected: relevance_score=0.0 below threshold 0.5"` or
`"rejected: missing title"` — so rejections are debuggable, not opaque.
Accepted resources also need a non-empty `url`/`title` and a URL that
isn't already stored for this cluster (`unique(cluster_id, url)` is
enforced at the database level too, not just in application logic).

```bash
# retrieve + validate + store resources for a cluster (default limit 5)
curl -X POST "http://127.0.0.1:8000/clusters/<cluster_id>/resources"

# list resources already stored for a cluster
curl http://127.0.0.1:8000/clusters/<cluster_id>/resources
```

Re-running retrieval for the same cluster never inserts duplicates —
candidates whose URL is already stored for that cluster are rejected as
duplicates during validation (and the database's unique constraint is the
backstop either way).

`POST /jobs/daily-batch` retrieves and validates resources for every
cluster it produces, right after clustering and before generating
cluster-level Revisit Cards — `summary_json` reports
`resources_retrieved`/`resources_accepted` for the whole run.
`GET /metrics/observability` reports `resources`: `total_resources`,
`resources_by_provider`, `average_resource_validation_score`,
`clusters_with_resources`, and (see below) the card-resource link counts.

## Resource-aware cluster Revisit Cards

Cluster-level Revisit Cards now use a cluster's validated resources as
**supporting context** — individual-capture cards are unchanged.

When a cluster-level card is created, up to the **top 5 accepted resources
for that cluster, ranked by `validation_score`**, are passed into
generation and explicitly linked to the resulting card via a
`revisit_card_resources` join row per resource (`unique(revisit_card_id,
resource_id)` at the database level). `GET /revisit-cards/{card_id}` and
`GET /revisit-cards` both return the linked resources under `resources`.

**Rule-based cards** append a plain, factual listing to `original_context`:

```
Related resources prepared:
- Sleep duration and cognitive performance: an overview
```

Only the resource's already-stored `title` is used — nothing is
paraphrased or embellished, so there's no way for the rule-based path to
invent a claim about a resource it's merely listing.

**LLM cards** receive the same resources as additional JSON context, with
explicit instructions: use them only as supporting context, never invent
details about a resource beyond its stored title/snippet/url, mention a
resource only if it's actually relevant, and if the resources are weak,
generic, or only loosely related, say so plainly rather than overstating
them. The model still outputs only the same 4 fields
(`title`/`why_saved`/`original_context`/`next_action`) — resources don't
add new output fields, just more (bounded, already-validated) input.

**Why resources are *linked* to the card, not just mentioned in its text**:
traceability. The card's prose is a one-time snapshot; the
`revisit_card_resources` rows are queryable structured data — "which
resources informed this card" survives independent of whatever the
generated text happened to say, and is what backs the observability
metrics below. It also means a UI could show "based on N resources" even
if the generated text didn't explicitly enumerate all of them (an LLM
card may, correctly, choose not to mention a weak resource in its prose
while it's still linked for the record).

**Resources are supporting context, not trusted evidence.** Nothing about
being "validated" (per the deterministic lexical-overlap check from the
previous milestone) means a resource is *true* or *authoritative* — it
only means it passed a cheap relevance/structural check. Cards should
read like "here's something that came up that might be relevant," not
"this is proven by this source."

```bash
# create a resource-aware cluster card (default: include_resources=true)
curl -X POST "http://127.0.0.1:8000/clusters/<cluster_id>/revisit-card"

# create one explicitly without resources
curl -X POST "http://127.0.0.1:8000/clusters/<cluster_id>/revisit-card?include_resources=false"

# LLM-generated, resource-aware
curl -X POST "http://127.0.0.1:8000/clusters/<cluster_id>/revisit-card?generation_method=llm&include_resources=true"
```

`GET /metrics/observability`'s `resources` section also now reports
`total_card_resource_links`, `cards_with_resources`, and
`average_resources_per_resource_aware_card` — separate from
`clusters_with_resources` (which counts clusters that *have* stored
resources, regardless of whether any card was ever generated from them).

The offline eval dataset (`evals/datasets/revisit_card_eval.jsonl`) now
includes two resource-aware cluster cases — one with genuinely relevant
resources (checking that they nudge specificity without being overclaimed)
and one with deliberately weak/generic resources (checking that the model
doesn't manufacture claims to justify including them). The eval runner's
deterministic checks now also flag any URL appearing in a generated card
that wasn't present in that case's own captures or resources — a direct,
generic check for invented sourcing, not just the case-specific
`forbidden_terms` lists.

## What this milestone implements

Capture create/list/get, content extraction, embeddings + semantic
similarity search, basic greedy clustering of embedded captures, rule-based
and LLM-generated Revisit Cards (for both individual captures and whole
clusters, with automatic fallback to rule-based), an offline eval harness to
compare the two generation methods, lightweight feedback tracking on
individual cards, a read-only observability endpoint summarizing pipeline
health, product usage, and eval freshness in one call, a synchronous
daily-batch endpoint that runs the whole
extract→embed→cluster→retrieve-resources→generate-card pipeline for
return-labeled captures in one call (with every run recorded as a job),
related-resource retrieval and validation for clusters, resource-aware
cluster-level Revisit Cards (with linked resources visible on the card,
individual cards unchanged), and a minimal **Backlog UI** — five browser
pages served directly by FastAPI (no separate build step) for creating
captures, browsing Revisit Cards, submitting feedback, inspecting clusters,
running the daily batch, and reading observability metrics — all backed by
**PostgreSQL** via SQLAlchemy (with the `pgvector` extension for embeddings),
schema managed through Alembic migrations. A Capture can have many individual
Revisit Cards, at most one embedding (unique constraint on
`capture_embeddings.capture_id`), and belongs to at most one cluster at a
time (unique constraint on `cluster_items.capture_id`). A Cluster can have
many Resources (unique constraint on `(cluster_id, url)`), and a Revisit
Card can be linked to many Resources via `revisit_card_resources` (unique
constraint on `(revisit_card_id, resource_id)`). Every Revisit Card
belongs to exactly one capture or one cluster, enforced by a database
check constraint, and can have many feedback events, each with an
optional 1-5 rating (also enforced by a check constraint). Background
workers (to replace the synchronous batch with a real scheduled job), a
real LLM-as-judge for resource relevance, more advanced clustering
algorithms, judge calibration, feeding real feedback back into the eval
dataset, and any form of real production monitoring (Prometheus/Grafana/alerting)
come later — every step (extract, embed, cluster, retrieve resources, generate
card, evaluate) is still triggered manually or via the UI.

## Backlog UI

A minimal browser UI is served by the same FastAPI process at `/app/*`.
No separate frontend build step, no npm, no separate server.

Open `http://127.0.0.1:8000` in a browser — it redirects automatically to
`/app/capture`.

### Pages

| Route | What it does |
|---|---|
| `/app/capture` | Form to create a capture |
| `/app/backlog` | View all Revisit Cards, submit feedback |
| `/app/clusters` | View active clusters, their captures and resources, generate cards |
| `/app/jobs` | Run the daily batch, inspect job history and summary |
| `/app/metrics` | Live observability dashboard |

### Creating a capture from the UI

1. Go to `/app/capture`
2. Choose a **source type** and **label** (`return` = research, `casual` = low-priority)
3. Fill in at least one of: URL, selected text, or note
4. Click **Save capture** — success shows the new capture ID

### Running the daily batch from the UI

1. Go to `/app/jobs`
2. Choose a generation method (`rule_based` or `llm`)
3. Click **Run batch** — the page blocks while it runs (synchronous, may take
   30–60 seconds with real embeddings and resource retrieval)
4. On success the summary appears inline with counts for every step

### Viewing Revisit Cards

1. Go to `/app/backlog`
2. Cards are split into **Cluster cards** and **Individual cards**
3. Each card shows title, why saved, context, next action, generation method,
   and any linked resources (with URLs and snippets)

### Submitting feedback

On any card in `/app/backlog`, click one of the five action buttons:
`opened`, `useful`, `not_useful`, `dismissed`, `next_action_taken`.

The event is logged immediately. Open `/app/metrics` → **Feedback** section
to see `total_feedback_events`, `counts_by_action`, `useful_rate`, and
`average_rating` update.

## Telemetry

Revisit records lightweight telemetry to three database tables so you can
monitor token usage, cost, and pipeline health without an external service.

### What is tracked

| Table | What it records |
|---|---|
| `llm_calls` | Every LLM invocation: model, token counts, estimated cost, latency, status, failure type |
| `agent_steps` | Each major batch-pipeline step: extraction, embedding, clustering, resource retrieval, card generation — with start/end timestamps, status, and small metadata summaries |
| `retrieval_events` | Each cluster's resource retrieval: provider used, candidate count, accepted count, latency, status |

### What is intentionally NOT stored

Raw prompt text, raw capture content, user notes, selected text, and any
other user-authored content are never written to telemetry tables. Only
identifiers, counts, status codes, model names, and timing are stored.

### How to view telemetry

**UI:** Navigate to `/app/telemetry` — shows an aggregate summary and the
50 most recent LLM calls.

**API endpoints:**

```
GET /telemetry/summary
  → total_llm_calls, tokens by model, estimated cost, latency averages,
    failed agent steps, retrieval event count

GET /telemetry/jobs/{job_id}/trace
  → ordered agent steps, LLM calls, and retrieval events for one job run,
    plus aggregate token/cost for that run

GET /telemetry/llm-calls?limit=50
  → recent LLM call rows in reverse chronological order
```

### How token/cost estimates work

Costs are estimated from a small static pricing table in
`app/services/telemetry.py`. The table lists `(input_usd_per_token,
output_usd_per_token)` pairs for common OpenAI models. Lookup is exact
match first, then prefix match (so `gpt-4o-mini-2025` maps to the
`gpt-4o-mini` row). Unknown models return `null` for cost. Update the
table when OpenAI changes prices.

### Privacy note

The telemetry service is append-only and stores no user content — only
metadata. The `llm_calls` table stores only: owner_type, owner_id, model
name, prompt version, token counts, cost, latency, and success/failure
status. The `agent_steps` table stores only step metadata (which
cluster/capture id was processed, what the output counts were). Full
prompts and model responses are never persisted.

---

## Authentication

Revisit uses simple single-user session-cookie auth. It is **disabled by
default** so local development requires no credentials. **Enable it before
deploying to any network-accessible host.**

### Local development (auth off)

No configuration needed. `AUTH_ENABLED` defaults to `false` when unset.
All API endpoints and UI pages are open.

### Production / shared host (auth on)

Set three env vars (in `.env` or your host's secrets manager):

```bash
AUTH_ENABLED=true
APP_USERNAME=your_username
APP_PASSWORD=a_strong_password
```

With `AUTH_ENABLED=true`:

- All `/app/*` UI pages redirect to `/login` until the user signs in.
- All mutation API endpoints (`POST /captures`, `POST /jobs/daily-batch`, etc.)
  return `401 Unauthorized` without a valid session cookie.
- Read-only endpoints (`GET /revisit-cards`, `GET /metrics/observability`,
  etc.) remain open — they expose no write surface.
- `/login` and `/health` are always accessible.

### Session lifetime

Sessions are stored in memory (no database table). A server restart clears
all active sessions; users will need to sign in again after a restart. This
is intentional for a single-user MVP — add a persistent session store only
once there's a real reason (multiple devices, rolling restarts).

### What this is not

This is single-user MVP auth — not multi-account, not OAuth, not RBAC.
The `APP_PASSWORD` is stored in your env/secrets, not hashed in a database.
If you need team access or user management, this is the wrong layer.

## Run locally

### Step 1 — start Postgres

```bash
make db-up          # docker compose up -d  (pgvector image, port 5432)
```

Or point `DATABASE_URL` at any Postgres 14+ instance with `pgvector` installed.

### Step 2 — install dependencies and apply migrations

```bash
make install        # python3 -m venv .venv && pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL; OPENAI_API_KEY optional
make migrate        # alembic upgrade head
```

### Step 3 — start the API server

```bash
make dev            # uvicorn app.main:app --reload
```

Server runs at `http://127.0.0.1:8000`. The browser UI is at `/app/capture`.

### Step 4 — seed demo data

```bash
make seed-demo      # creates 4 demo captures + runs the daily batch
# or wipe first:
make seed-demo ARGS=--clear
```

### Step 5 — open the UI

| URL | Page |
|---|---|
| `http://127.0.0.1:8000/app/capture`  | Create a capture |
| `http://127.0.0.1:8000/app/backlog`  | View Revisit Cards, submit feedback |
| `http://127.0.0.1:8000/app/clusters` | Inspect clusters and resources |
| `http://127.0.0.1:8000/app/jobs`     | Run daily batch, view job history |
| `http://127.0.0.1:8000/app/metrics`  | Observability dashboard |

### Step 6 — run the eval harness

```bash
make eval           # python -m evals.run_revisit_card_eval
```

Reports are written to `evals/reports/`. Without `OPENAI_API_KEY` only the
rule-based path is evaluated (no LLM judge).

## Demo walkthrough

The recommended 5-minute demo flow:

1. **Seed demo data** (`make seed-demo`) — creates two related AI/ML captures,
   one unrelated capture, one casual capture, and runs the full pipeline.

2. **Open `/app/backlog`** — you should see a cluster-level Revisit Card
   for the two AI captures and optionally one for the sourdough capture,
   each with linked resources.

3. **Submit feedback** — click `opened` then `useful` on the cluster card.

4. **Open `/app/metrics`** — the Feedback section should show
   `total_feedback_events: 2` and `useful_rate: 1.0`.

5. **Create a new capture** — go to `/app/capture`, save a new article or
   passage with `label: return`, then run the batch again via `/app/jobs`.
   The new capture clusters with existing ones or creates a new cluster, and
   a new card appears in the backlog.

6. **Re-run the batch** (`/app/jobs` → Run batch) — because the existing
   cluster is unchanged, its card is *reused* (`cards_reused: 1`) rather
   than regenerated; only the new capture's cluster gets a new card.

## Deploying to Render

The simplest production path: Render web service + Render managed Postgres.
No Docker needed — Render auto-detects Python from `requirements.txt`.

### One-time setup

**1. Push to GitHub** (public or private repo, your choice).

**2. Create a Blueprint deployment**

In the [Render dashboard](https://dashboard.render.com):
→ New → Blueprint → connect your GitHub repo → select this repo.

Render reads `render.yaml` and creates:
- A Python web service running gunicorn
- A managed Postgres 16 database with pgvector available

**3. Set secrets in the Render dashboard**

`render.yaml` leaves four values unset (`sync: false`) — you must fill them in
the Render dashboard under **Environment → Environment Variables**:

| Variable | Value |
|---|---|
| `APP_USERNAME` | Your login username |
| `APP_PASSWORD` | A strong password |
| `OPENAI_API_KEY` | Your OpenAI key (optional — embeddings/LLM fall back without it) |
| `SEARCH_API_KEY` | Brave Search API key (optional — only if you set `SEARCH_PROVIDER=brave`) |

**4. Deploy**

Click **Deploy**. Render will:
1. `pip install -r requirements.txt`
2. Run `bash scripts/start.sh`, which runs `alembic upgrade head` then starts gunicorn

### Verify

```bash
curl https://<your-service>.onrender.com/health
# → {"status": "ok"}

# open in browser
https://<your-service>.onrender.com/login
```

### Free-tier caveats

- **Web service** spins down after 15 minutes of inactivity; first request after
  spin-down takes ~30 seconds.
- **Postgres free plan** expires after 90 days and the database is deleted.
  Upgrade to the "Starter" plan ($7/month) before the expiry date to retain data.
- **Pre-deploy commands are not supported on the free tier.** Migrations run
  at startup inside `scripts/start.sh` instead. This is fine for a
  single-instance personal deployment — there is no risk of two instances
  racing to migrate simultaneously. On a paid plan with multiple instances,
  move `alembic upgrade head` back to a proper pre-deploy step.

### Railway (alternative)

Railway picks up the `Procfile` automatically:

```
web: bash scripts/start.sh
```

Provision a Postgres plugin in the Railway dashboard and enable the pgvector
extension from the Railway query console (`CREATE EXTENSION IF NOT EXISTS vector`).
Migrations run automatically on first startup via `scripts/start.sh`.

### Production start command (reference)

```bash
bash scripts/start.sh
# expands to:
#   alembic upgrade head
#   gunicorn -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8000} --timeout 120 app.main:app
```

`--timeout 120` is required because `POST /jobs/daily-batch` is synchronous
and can take 30–90 seconds with real embeddings and resource retrieval.

## Running tests

```bash
make db-test-setup  # once: creates revisit_test database (requires db-up)
make test           # pytest tests/ -v
```

Tests hit a real `revisit_test` PostgreSQL database. Fake embeddings are
used (no `OPENAI_API_KEY` needed). Every test starts with all tables
truncated for isolation.

## Running the server (legacy reference)

Start Postgres:

After changing a model in `app/models/`, generate a new migration with:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Trying the endpoints

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Create a capture:

```bash
curl -X POST http://127.0.0.1:8000/captures \
  -H "Content-Type: application/json" \
  -d '{
        "source_type": "article",
        "url": "https://example.com/some-article",
        "title": "Some Article",
        "label": "return"
      }'
```

List all captures:

```bash
curl http://127.0.0.1:8000/captures
```

Get a single capture by id:

```bash
curl http://127.0.0.1:8000/captures/<capture_id>
```

Run extraction on that capture:

```bash
curl -X POST http://127.0.0.1:8000/captures/<capture_id>/extract
```

Create an embedding for that capture (requires extraction to have run first):

```bash
curl -X POST http://127.0.0.1:8000/captures/<capture_id>/embed
```

Find captures most similar to it:

```bash
curl "http://127.0.0.1:8000/captures/<capture_id>/similar?limit=5"
```

Create a rule-based Revisit Card for that capture (default):

```bash
curl -X POST http://127.0.0.1:8000/captures/<capture_id>/revisit-card
```

Create an LLM-generated Revisit Card for that capture instead (requires
`OPENAI_API_KEY`; falls back to rule-based if it's missing or the call
fails):

```bash
curl -X POST "http://127.0.0.1:8000/captures/<capture_id>/revisit-card?generation_method=llm"
```

List all Revisit Cards:

```bash
curl http://127.0.0.1:8000/revisit-cards
```

Get a single Revisit Card by id:

```bash
curl http://127.0.0.1:8000/revisit-cards/<card_id>
```

Run clustering over all embedded captures (default threshold 0.60):

```bash
curl -X POST "http://127.0.0.1:8000/clusters/run"
```

Run it with a different threshold:

```bash
curl -X POST "http://127.0.0.1:8000/clusters/run?similarity_threshold=0.7"
```

List all clusters:

```bash
curl http://127.0.0.1:8000/clusters
```

Get a single cluster and its captures:

```bash
curl http://127.0.0.1:8000/clusters/<cluster_id>
```

Create a rule-based Revisit Card for a whole cluster (default):

```bash
curl -X POST http://127.0.0.1:8000/clusters/<cluster_id>/revisit-card
```

Create an LLM-generated Revisit Card for a whole cluster instead:

```bash
curl -X POST "http://127.0.0.1:8000/clusters/<cluster_id>/revisit-card?generation_method=llm"
```

Captures, Revisit Cards, embeddings, and clusters persist in Postgres across
server restarts.
