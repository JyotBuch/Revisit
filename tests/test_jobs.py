"""Tests for the jobs API and daily batch trigger."""


def test_list_jobs_empty(client):
    r = client.get("/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_get_job_not_found(client):
    r = client.get("/jobs/no-such-id")
    assert r.status_code == 404


def test_run_daily_batch_records_job(client):
    r = client.post("/jobs/daily-batch")
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "succeeded"
    assert job["job_type"] == "daily_batch"
    assert job["summary_json"] is not None

    # Job must appear in the list
    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job["id"]


def test_run_daily_batch_summary_keys(client):
    job = client.post("/jobs/daily-batch").json()
    summary = job["summary_json"]
    expected_keys = {
        "captures_considered", "captures_extracted", "extraction_failures",
        "embeddings_created", "clusters_created", "clusters_reused",
        "clusters_archived", "resources_retrieved", "resources_accepted",
        "cards_created", "cards_reused", "cards_with_resources",
        "generation_method_requested",
    }
    assert expected_keys.issubset(summary.keys())


def test_run_daily_batch_with_llm_method(client):
    """Requesting llm method must still succeed (falls back to rule_based
    when OPENAI_API_KEY is absent, which it always is in tests)."""
    r = client.post("/jobs/daily-batch?generation_method=llm")
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "succeeded"
    assert job["summary_json"]["generation_method_requested"] == "llm"


def test_get_job_by_id(client):
    created = client.post("/jobs/daily-batch").json()
    r = client.get(f"/jobs/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
