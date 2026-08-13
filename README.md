# Revisit

You save things with the intention of returning to them. You rarely do.

Revisit is a capture-to-research newsletter. Select text on any webpage and choose **Research** or **Capture**. Revisit records the passage and page context without requiring a form; research selections become a sourced nightly briefing, while capture-only selections stay in your library.

---

## How it works

**1. Capture** — Select text in Chrome. An inline `Research | Capture` bubble records the passage, URL, page title, domain, and available metadata. Notes are optional.

**2. Research** — A queued nightly job independently researches each new `Research` selection using web sources and produces a concise synthesis and follow-up question. Embeddings and clustering are intentionally not part of the production path.

**3. Newsletter** — The web app presents each dated issue with the original selections, research summaries, sources, and prompts to keep thinking. Users can also request an immediate issue with **Run now**.

---

## Key concepts

| Concept | What it is |
|---|---|
| **Capture** | The raw save: a URL, selected text, image, video, or note. Tagged `return` or `casual`. |
| **Cluster** | Related captures grouped by semantic similarity. The unit the research agent works on. |
| **Research pass** | An agentic tool-calling loop: search → read full articles → iterate → synthesize. Runs once per `return` cluster per batch. |
| **Revisit Card** | The output: title, why you saved it, what the research found, what to do next. |
| **Backlog** | All your cards in one place. Mark each one useful / not useful to tune future research quality. |

---

## Quick start (local)

**Prerequisites:** Docker (for Postgres), Python 3.11+

```bash
# 1. Start Postgres with pgvector
make db-up

# 2. Install dependencies and apply migrations
make install
cp .env.example .env   # fill in DATABASE_URL; add OPENAI_API_KEY + TAVILY_API_KEY for research
make migrate

# 3. Start the server
make dev
# → http://127.0.0.1:8000
```

**Try it with demo data:**

```bash
make seed-demo          # creates sample captures and runs the batch pipeline
# open http://127.0.0.1:8000/app/backlog
```

---

## The UI

| Page | What you do there |
|---|---|
| `/app/capture` | Save a new capture |
| `/app/backlog` | Read Revisit Cards, submit feedback |
| `/app/clusters` | Inspect how your captures were grouped |
| `/app/jobs` | Run the batch pipeline manually, view job history |
| `/app/metrics` | Pipeline health, card quality, token usage |
| `/app/telemetry` | Per-run LLM call trace, cost breakdown |

---

## The research agent

When the batch runs with `generation_method=llm`, a tool-calling agent runs on each `return` cluster:

1. Reads your captures to understand what you were trying to learn
2. Runs targeted searches (not just the cluster title — it reasons about what to look for)
3. Reads full articles via `trafilatura`, not just search snippets
4. Iterates: if a search turns up a useful article that mentions a related angle, it searches that too
5. Calls `finish()` with structured notes when it has enough

The resulting notes feed directly into the Revisit Card. Each article the agent reads is stored in the database and linked to the card, so you can see exactly what it found.

**Without API keys**, the agent falls back gracefully: no `OPENAI_API_KEY` or `TAVILY_API_KEY` → cards are still generated rule-based. No partial failures.

**Environment variables for the research path:**

| Variable | Required | Default |
|---|---|---|
| `OPENAI_API_KEY` | For LLM cards + embeddings | Falls back to fake |
| `TAVILY_API_KEY` | For web search in the agent | Falls back to fake provider |
| `OPENAI_RESEARCH_MODEL` | No | `gpt-4o-mini` |
| `RESEARCH_MAX_ITERATIONS` | No | `6` |

---

## Deployment (Render)

The simplest path: **Render web service + Render managed Postgres**.

**1.** Push this repo to GitHub.

**2.** In the [Render dashboard](https://dashboard.render.com): New → Blueprint → connect your repo. Render reads `render.yaml` and creates a Python web service and a Postgres database with pgvector.

**3.** Set these secrets in Render's Environment settings:

| Variable | What it is |
|---|---|
| `APP_USERNAME` | Your login username |
| `APP_PASSWORD` | A strong password |
| `OPENAI_API_KEY` | For embeddings and LLM card generation |
| `TAVILY_API_KEY` | For web search in the research agent |

**4.** Deploy. Migrations run automatically on startup.

**Free tier note:** The web service spins down after 15 minutes idle (first request after spin-down takes ~30s). The free Postgres plan expires after 90 days — upgrade to Starter ($7/month) before then.

**Alternative:** Railway picks up the `Procfile` automatically. Provision a Postgres plugin and enable `pgvector` from the Railway query console.

---

## Authentication

Auth is **off by default** so local dev needs no credentials.

To protect a deployed instance, set:

```bash
AUTH_ENABLED=true
APP_USERNAME=your_username
APP_PASSWORD=a_strong_password
```

Sessions persist across restarts (stored in the database). Sessions expire after 7 days.

---

## Running tests

```bash
make db-test-setup   # once: creates revisit_test database (requires db-up)
make test            # pytest tests/
```

Tests hit a real Postgres database. Fake embeddings are used (no API key needed). All tables are truncated between tests.

---

## Browser extension

A Manifest V3 Chrome extension lives in `extension/`. Install it unpacked from `chrome://extensions` during development. Selecting text opens the inline `Research | Capture` bubble; popup, hotkey, and context-menu flows are included as fallbacks. Configure the production backend and Chrome OAuth client as described in `extension/README.md`.

---

## Technical reference

For implementation details — schema, algorithm choices, API endpoints, eval harness, telemetry internals — see [FUNCTIONALITY.md](FUNCTIONALITY.md).
