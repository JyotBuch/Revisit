#!/usr/bin/env python3
"""Seed demo data for a local Revisit walkthrough.

Creates a small set of captures, then (if OPENAI_API_KEY is present) runs
the full daily batch: extract → embed → cluster → retrieve resources →
generate Revisit Cards.

Run from the project root with the venv active:

    python scripts/seed_demo_data.py [--clear]

Flags:
    --clear   Delete all existing data before seeding (default: False).
              Without it, seed data is additive; existing data is untouched.
"""

import argparse
import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()  # picks up .env if present

from sqlalchemy import text

from app.db import SessionLocal, engine
# Import all ORM models so SQLAlchemy can resolve relationship() strings
# before any service code runs.  The same pattern is used in alembic/env.py.
from app.models import (  # noqa: F401
    capture, capture_embedding, cluster, job,
    resource, revisit_card, revisit_card_feedback, revisit_card_resource,
)
from app.schemas.capture import CaptureCreate, CaptureLabel, SourceType
from app.services import capture_store, batch


DEMO_CAPTURES = [
    # Two related ML/AI captures — should cluster together.
    CaptureCreate(
        source_type=SourceType.article,
        url="https://arxiv.org/abs/1706.03762",
        title="Attention Is All You Need",
        selected_text=(
            "Transformers rely entirely on attention mechanisms to draw global "
            "dependencies between input and output, dispensing with recurrence "
            "and convolutions. The architecture proves remarkably effective on "
            "machine translation and achieves new state-of-the-art results."
        ),
        user_note="Key paper behind GPT, BERT, and every modern LLM. Come back to understand multi-head attention.",
        label=CaptureLabel.return_,
    ),
    CaptureCreate(
        source_type=SourceType.passage,
        selected_text=(
            "Self-attention allows each position in the sequence to attend to "
            "all positions in the previous layer. This enables capturing long-range "
            "dependencies far more effectively than RNNs, and is the core "
            "mechanism that makes large language models work."
        ),
        title="Self-attention explained",
        user_note="Good intuition-builder for how transformers differ from RNNs.",
        label=CaptureLabel.return_,
    ),
    # One unrelated capture — should land in its own cluster.
    CaptureCreate(
        source_type=SourceType.article,
        url="https://example.com/sourdough-bread",
        title="Why sourdough needs 18-hour fermentation",
        user_note="Trying to get consistent oven spring. Long cold proof seems key.",
        label=CaptureLabel.return_,
    ),
    # One casual capture — not processed by the daily batch.
    CaptureCreate(
        source_type=SourceType.note,
        user_note="Check if the library supports async context managers.",
        label=CaptureLabel.casual,
    ),
]

BASE_URL = "http://127.0.0.1:8000"


def _clear_all(db) -> None:
    tables = [
        "revisit_card_resources", "revisit_card_feedback", "revisit_cards",
        "resources", "cluster_items", "clusters", "capture_embeddings",
        "captures", "jobs",
    ]
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        conn.commit()
    print("✓ Cleared all existing data.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true",
                        help="Clear all existing data before seeding.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.clear:
            _clear_all(db)

        print("Creating demo captures…")
        created_ids = []
        for cap_data in DEMO_CAPTURES:
            cap = capture_store.create_capture(db, cap_data)
            label = cap.label.value if hasattr(cap.label, "value") else cap.label
            print(f"  ✓ [{label}] {cap.title or cap.user_note[:50]!r}")
            created_ids.append(cap.id)

        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        if has_openai:
            print("\nOPENAI_API_KEY is set — running full daily batch (extract → embed → cluster → cards)…")
        else:
            print("\nOPENAI_API_KEY not set — running batch with fake embeddings and rule-based cards…")

        print("Running daily batch…")
        job = batch.run_daily_batch(db, generation_method="rule_based")
        s = job.summary_json or {}
        print(f"  ✓ Batch {job.status}")
        print(f"    captures considered : {s.get('captures_considered', '?')}")
        print(f"    extractions         : {s.get('captures_extracted', '?')} ok / {s.get('extraction_failures', '?')} failed")
        print(f"    embeddings created  : {s.get('embeddings_created', '?')}")
        print(f"    clusters created    : {s.get('clusters_created', '?')}, reused: {s.get('clusters_reused', '?')}, archived: {s.get('clusters_archived', '?')}")
        print(f"    resources accepted  : {s.get('resources_accepted', '?')}")
        print(f"    cards created       : {s.get('cards_created', '?')}, reused: {s.get('cards_reused', '?')}")

        print("\n─── UI pages ───────────────────────────────────────────")
        for path, label in [
            ("/app/capture",  "Create a capture   "),
            ("/app/backlog",  "View Revisit Cards "),
            ("/app/clusters", "Inspect clusters   "),
            ("/app/jobs",     "Job history        "),
            ("/app/metrics",  "Observability      "),
        ]:
            print(f"  {label}  {BASE_URL}{path}")
        print("────────────────────────────────────────────────────────\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
