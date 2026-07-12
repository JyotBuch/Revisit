"""Integration tests for the telemetry service and API.

All tests run against revisit_test. No OPENAI_API_KEY required.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import telemetry as tel


# ---------------------------------------------------------------------------
# record_llm_call
# ---------------------------------------------------------------------------

def test_record_llm_call_stores_tokens_and_cost(db: Session) -> None:
    row = tel.record_llm_call(
        db,
        purpose="revisit_card_generation",
        model_name="gpt-4o-mini",
        prompt_version="v2",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        latency_ms=450,
        status="succeeded",
    )
    db.commit()
    assert row.id is not None
    assert row.input_tokens == 200
    assert row.output_tokens == 100
    assert row.total_tokens == 300
    assert row.latency_ms == 450
    assert row.status == "succeeded"
    assert row.estimated_cost_usd is not None
    assert row.estimated_cost_usd > 0


def test_record_llm_call_failed_stores_failure_type(db: Session) -> None:
    row = tel.record_llm_call(
        db,
        purpose="revisit_card_generation",
        model_name="gpt-4o-mini",
        latency_ms=50,
        status="failed",
        failure_type="AuthenticationError",
    )
    db.commit()
    assert row.status == "failed"
    assert row.failure_type == "AuthenticationError"
    assert row.estimated_cost_usd is None


def test_record_llm_call_with_job_id(db: Session) -> None:
    row = tel.record_llm_call(
        db,
        job_id="job-abc",
        owner_type="cluster",
        owner_id="cluster-xyz",
        purpose="revisit_card_generation",
        model_name="gpt-4o",
        input_tokens=500,
        output_tokens=200,
        total_tokens=700,
        latency_ms=1200,
        status="succeeded",
    )
    db.commit()
    assert row.job_id == "job-abc"
    assert row.owner_type == "cluster"
    assert row.owner_id == "cluster-xyz"


# ---------------------------------------------------------------------------
# agent steps
# ---------------------------------------------------------------------------

def test_start_and_complete_agent_step(db: Session) -> None:
    step = tel.start_agent_step(
        db,
        job_id="job-1",
        step_name="extract_capture",
        owner_type="capture",
        owner_id="cap-1",
        input_summary={"status_before": "saved"},
    )
    db.commit()
    assert step.status == "started"
    assert step.completed_at is None

    tel.complete_agent_step(db, step.id, output_summary={"status_after": "extracted"})
    db.commit()
    assert step.status == "succeeded"
    assert step.completed_at is not None
    assert step.latency_ms is not None and step.latency_ms >= 0
    assert step.output_summary_json == {"status_after": "extracted"}


def test_fail_agent_step_stores_error(db: Session) -> None:
    step = tel.start_agent_step(db, step_name="embed_capture")
    db.commit()

    tel.fail_agent_step(db, step.id, error="OOMError: out of memory")
    db.commit()

    assert step.status == "failed"
    assert "OOMError" in step.error
    assert step.latency_ms is not None


def test_job_trace_returns_steps_in_order(db: Session) -> None:
    import time as _time

    job_id = "job-order-test"
    s1 = tel.start_agent_step(db, job_id=job_id, step_name="daily_batch")
    db.commit()
    _time.sleep(0.01)
    s2 = tel.start_agent_step(db, job_id=job_id, step_name="run_clustering")
    tel.complete_agent_step(db, s2.id)
    tel.complete_agent_step(db, s1.id)
    db.commit()

    trace = tel.get_job_trace(db, job_id)
    step_names = [s["step_name"] for s in trace["agent_steps"]]
    assert step_names == ["daily_batch", "run_clustering"]


def test_job_trace_includes_llm_calls_and_retrieval(db: Session) -> None:
    job_id = "job-trace-full"
    tel.record_llm_call(
        db, job_id=job_id, purpose="revisit_card_generation",
        model_name="gpt-4o-mini", status="succeeded",
        input_tokens=100, output_tokens=50, total_tokens=150, latency_ms=300,
    )
    tel.record_retrieval_event(
        db, job_id=job_id, cluster_id="cl-1", query="neural networks",
        provider="fake-local-dev-v1", num_candidates=5, num_accepted=3,
        latency_ms=80, status="succeeded",
    )
    db.commit()

    trace = tel.get_job_trace(db, job_id)
    assert len(trace["llm_calls"]) == 1
    assert len(trace["retrieval_events"]) == 1
    assert trace["aggregate"]["total_tokens"] == 150
    assert trace["aggregate"]["estimated_cost_usd"] > 0


# ---------------------------------------------------------------------------
# telemetry summary
# ---------------------------------------------------------------------------

def test_telemetry_summary_empty_db(db: Session) -> None:
    summary = tel.get_telemetry_summary(db)
    assert summary["total_llm_calls"] == 0
    assert summary["total_tokens"] == 0
    assert summary["estimated_cost_usd"] is None
    assert summary["average_llm_latency_ms"] is None
    assert summary["failed_agent_steps"] == 0
    assert summary["retrieval_events"] == 0
    assert summary["average_retrieval_latency_ms"] is None


def test_telemetry_summary_with_data(db: Session) -> None:
    tel.record_llm_call(
        db, purpose="revisit_card_generation", model_name="gpt-4o-mini",
        input_tokens=100, output_tokens=50, total_tokens=150,
        latency_ms=400, status="succeeded",
    )
    tel.record_llm_call(
        db, purpose="revisit_card_generation", model_name="gpt-4o-mini",
        latency_ms=100, status="failed", failure_type="TimeoutError",
    )
    tel.start_agent_step(db, step_name="embed_capture")
    failed = tel.start_agent_step(db, step_name="extract_capture")
    tel.fail_agent_step(db, failed.id, error="boom")
    tel.record_retrieval_event(
        db, cluster_id="c1", query="test", provider="brave",
        num_candidates=5, num_accepted=3, latency_ms=200, status="succeeded",
    )
    db.commit()

    summary = tel.get_telemetry_summary(db)
    assert summary["total_llm_calls"] == 2
    assert summary["llm_calls_by_status"]["succeeded"] == 1
    assert summary["llm_calls_by_status"]["failed"] == 1
    assert summary["total_tokens"] == 150
    assert "gpt-4o-mini" in summary["tokens_by_model"]
    assert summary["estimated_cost_usd"] is not None and summary["estimated_cost_usd"] > 0
    assert summary["average_llm_latency_ms"] == 400.0
    assert summary["failed_agent_steps"] == 1
    assert summary["retrieval_events"] == 1
    assert summary["average_retrieval_latency_ms"] == 200.0


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def test_telemetry_summary_endpoint(client: TestClient) -> None:
    resp = client.get("/telemetry/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "total_llm_calls" in body
    assert "total_tokens" in body
    assert "failed_agent_steps" in body


def test_telemetry_llm_calls_endpoint_empty(client: TestClient) -> None:
    resp = client.get("/telemetry/llm-calls")
    assert resp.status_code == 200
    assert resp.json() == []


def test_telemetry_llm_calls_endpoint_with_data(client: TestClient, db: Session) -> None:
    tel.record_llm_call(
        db, purpose="revisit_card_generation", model_name="gpt-4o-mini",
        input_tokens=10, output_tokens=5, total_tokens=15,
        latency_ms=200, status="succeeded",
    )
    db.commit()

    resp = client.get("/telemetry/llm-calls?limit=10")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["model_name"] == "gpt-4o-mini"
    assert rows[0]["status"] == "succeeded"


def test_telemetry_job_trace_endpoint(client: TestClient, db: Session) -> None:
    job_id = "job-api-trace"
    tel.start_agent_step(db, job_id=job_id, step_name="daily_batch")
    tel.record_llm_call(
        db, job_id=job_id, purpose="revisit_card_generation",
        model_name="gpt-4o-mini", status="succeeded",
        input_tokens=50, output_tokens=25, total_tokens=75, latency_ms=100,
    )
    db.commit()

    resp = client.get(f"/telemetry/jobs/{job_id}/trace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert len(body["agent_steps"]) == 1
    assert len(body["llm_calls"]) == 1
    assert body["aggregate"]["llm_call_count"] == 1


# ---------------------------------------------------------------------------
# Observability endpoint includes telemetry section
# ---------------------------------------------------------------------------

def test_observability_includes_telemetry_section(client: TestClient) -> None:
    resp = client.get("/metrics/observability")
    assert resp.status_code == 200
    body = resp.json()
    assert "telemetry" in body
    t = body["telemetry"]
    assert "total_llm_calls" in t
    assert "total_tokens" in t
    assert "failed_agent_steps" in t
    assert "retrieval_events" in t


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def test_estimate_cost_known_model() -> None:
    cost = tel.estimate_cost("gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost is not None
    assert abs(cost - (0.15 + 0.60)) < 0.001


def test_estimate_cost_unknown_model() -> None:
    cost = tel.estimate_cost("some-future-model-xyz", input_tokens=100, output_tokens=50)
    assert cost is None


def test_estimate_cost_prefix_match() -> None:
    cost = tel.estimate_cost("gpt-4o-mini-2025", input_tokens=0, output_tokens=0)
    assert cost == 0.0
