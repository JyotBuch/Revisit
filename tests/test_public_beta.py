import uuid

from app import auth
from app.main import app
from app.models.capture import CaptureORM
from app.models.job import JobORM
from app.models.user import UserORM
from app.schemas.capture import CaptureLabel, SourceType
from app.schemas.job import JobStatus, JobType
from app.services.newsletter import run_newsletter_batch
from app.services.newsletter import _safe_web_url, _search
from app.services.inline_research import run_inline_research_job


def make_user(db, email="reader@example.com"):
    user = UserORM(id=str(uuid.uuid4()), google_sub=str(uuid.uuid4()), email=email, timezone="UTC")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_public_capture_maps_modes_and_is_idempotent(client, db):
    user = make_user(db)
    app.dependency_overrides[auth.current_user] = lambda: user
    payload = {
        "source_type": "passage", "url": "https://example.com/read",
        "title": "An idea", "selected_text": "A passage to investigate",
        "domain": "example.com", "mode": "research", "idempotency_key": "same-key-123",
    }
    first = client.post("/api/v1/captures", json=payload)
    second = client.post("/api/v1/captures", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["label"] == "return"
    app.dependency_overrides.pop(auth.current_user, None)


def test_public_capture_lists_only_current_user(client, db):
    user, other = make_user(db), make_user(db, "other@example.com")
    db.add_all([
        CaptureORM(id=str(uuid.uuid4()), user_id=user.id, source_type=SourceType.note, user_note="mine", label=CaptureLabel.casual),
        CaptureORM(id=str(uuid.uuid4()), user_id=other.id, source_type=SourceType.note, user_note="theirs", label=CaptureLabel.casual),
    ])
    db.commit()
    app.dependency_overrides[auth.current_user] = lambda: user
    response = client.get("/api/v1/captures")
    assert response.status_code == 200
    assert [row["user_note"] for row in response.json()] == ["mine"]
    app.dependency_overrides.pop(auth.current_user, None)


def test_clear_captures_deletes_only_current_users_rows(client, db):
    user, other = make_user(db), make_user(db, "clear-other@example.com")
    mine = CaptureORM(id=str(uuid.uuid4()), user_id=user.id, source_type=SourceType.note, user_note="mine", label=CaptureLabel.casual)
    theirs = CaptureORM(id=str(uuid.uuid4()), user_id=other.id, source_type=SourceType.note, user_note="theirs", label=CaptureLabel.casual)
    db.add_all([mine, theirs])
    db.commit()
    app.dependency_overrides[auth.current_user] = lambda: user

    response = client.delete("/api/v1/captures")

    assert response.status_code == 204
    db.expire_all()
    assert db.get(CaptureORM, mine.id) is None
    assert db.get(CaptureORM, theirs.id) is not None
    app.dependency_overrides.pop(auth.current_user, None)


def test_newsletter_uses_research_captures_only(db, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    user = make_user(db)
    research = CaptureORM(id=str(uuid.uuid4()), user_id=user.id, source_type=SourceType.passage, selected_text="research me", title="Research", label=CaptureLabel.return_)
    capture = CaptureORM(id=str(uuid.uuid4()), user_id=user.id, source_type=SourceType.passage, selected_text="save only", title="Capture", label=CaptureLabel.casual)
    job = JobORM(id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.daily_batch, status=JobStatus.running)
    db.add_all([research, capture, job])
    db.commit()
    issue = run_newsletter_batch(db, user_id=user.id, job_id=job.id)
    assert issue is not None
    assert [item["capture_id"] for item in issue.items_json] == [research.id]
    assert db.get(JobORM, job.id).status == JobStatus.succeeded


def test_newsletter_source_urls_reject_active_schemes():
    assert _safe_web_url("javascript:alert(1)") is None
    assert _safe_web_url("data:text/html,pwned") is None
    assert _safe_web_url("https://example.com/article") == "https://example.com/article"


def test_newsletter_search_prioritizes_user_question(monkeypatch):
    observed = {}

    class SearchResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    def fake_post(url, *, json, timeout):
        observed.update(json)
        return SearchResponse()

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr("app.services.newsletter.requests.post", fake_post)
    capture = CaptureORM(
        id=str(uuid.uuid4()), source_type=SourceType.passage, label=CaptureLabel.return_,
        title="Open versus closed AI", selected_text="Should models be open?",
        user_note="What have other AI leaders said about this?",
    )

    _search(capture)

    assert observed["query"].startswith("What have other AI leaders said about this?")
    assert "Open versus closed AI" in observed["query"]


def test_public_capture_rejects_non_web_url(client, db):
    user = make_user(db)
    app.dependency_overrides[auth.current_user] = lambda: user
    response = client.post("/api/v1/captures", json={
        "source_type": "passage", "url": "javascript:alert(1)",
        "selected_text": "unsafe link", "mode": "capture", "idempotency_key": "unsafe-url-123",
    })
    assert response.status_code == 422
    app.dependency_overrides.pop(auth.current_user, None)


def test_inline_free_tier_job_creates_newsletter(db, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    user = make_user(db)
    capture = CaptureORM(
        id=str(uuid.uuid4()), user_id=user.id, source_type=SourceType.passage,
        selected_text="research inline", title="Inline", label=CaptureLabel.return_,
    )
    job = JobORM(
        id=str(uuid.uuid4()), user_id=user.id, job_type=JobType.daily_batch,
        status=JobStatus.queued,
    )
    db.add_all([capture, job])
    db.commit()

    run_inline_research_job(job.id, user.id)

    db.expire_all()
    assert db.get(JobORM, job.id).status == JobStatus.succeeded
    assert db.get(JobORM, job.id).summary_json["newsletter_created"] is True
