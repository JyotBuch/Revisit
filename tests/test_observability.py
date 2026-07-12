"""Tests for the observability metrics endpoint."""

EXPECTED_SECTIONS = {"pipeline", "revisit_cards", "feedback", "eval", "jobs", "resources", "telemetry"}

PIPELINE_KEYS = {
    "total_captures", "captures_by_status", "captures_by_source_type",
    "total_extracted", "total_failed_extraction", "total_embeddings",
    "total_clusters", "total_cluster_items", "singleton_clusters",
    "active_clusters", "archived_clusters",
}

REVISIT_CARD_KEYS = {
    "total_revisit_cards", "cards_by_type", "cards_by_generation_method",
    "llm_card_count", "rule_based_card_count",
}

FEEDBACK_KEYS = {
    "total_feedback_events", "feedback_counts_by_action",
    "average_rating", "useful_rate", "dismiss_rate",
}

EVAL_KEYS = {
    "latest_eval_report_path", "latest_eval_timestamp",
    "latest_rule_based_pass_rate", "latest_llm_pass_rate",
}

JOB_KEYS = {
    "total_jobs", "jobs_by_status",
    "latest_daily_batch_status", "latest_daily_batch_started_at",
}

RESOURCE_KEYS = {
    "total_resources", "resources_by_provider", "average_resource_validation_score",
    "clusters_with_resources", "total_card_resource_links", "cards_with_resources",
}


def test_observability_top_level_sections(client):
    r = client.get("/metrics/observability")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == EXPECTED_SECTIONS


def test_observability_pipeline_keys(client):
    r = client.get("/metrics/observability")
    pipeline = r.json()["pipeline"]
    assert PIPELINE_KEYS.issubset(pipeline.keys())


def test_observability_revisit_cards_keys(client):
    r = client.get("/metrics/observability")
    rc = r.json()["revisit_cards"]
    assert REVISIT_CARD_KEYS.issubset(rc.keys())


def test_observability_feedback_keys(client):
    r = client.get("/metrics/observability")
    fb = r.json()["feedback"]
    assert FEEDBACK_KEYS.issubset(fb.keys())


def test_observability_eval_keys(client):
    r = client.get("/metrics/observability")
    ev = r.json()["eval"]
    assert EVAL_KEYS.issubset(ev.keys())


def test_observability_jobs_keys(client):
    r = client.get("/metrics/observability")
    jb = r.json()["jobs"]
    assert JOB_KEYS.issubset(jb.keys())


def test_observability_resources_keys(client):
    r = client.get("/metrics/observability")
    res = r.json()["resources"]
    assert RESOURCE_KEYS.issubset(res.keys())


def test_observability_counts_reflect_data(client):
    """Counts increment correctly as captures and cards are created."""
    r0 = client.get("/metrics/observability").json()
    assert r0["pipeline"]["total_captures"] == 0
    assert r0["revisit_cards"]["total_revisit_cards"] == 0

    cap = client.post("/captures", json={
        "source_type": "note",
        "user_note": "Test note",
        "label": "return",
    }).json()
    client.post(f"/captures/{cap['id']}/revisit-card")

    r1 = client.get("/metrics/observability").json()
    assert r1["pipeline"]["total_captures"] == 1
    assert r1["revisit_cards"]["total_revisit_cards"] == 1
    assert r1["revisit_cards"]["rule_based_card_count"] == 1
