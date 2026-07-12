"""Tests for the capture API endpoints."""

VALID_PAYLOAD = {
    "source_type": "article",
    "url": "https://example.com/test",
    "title": "Test Article",
    "label": "return",
}


def test_create_capture_valid(client):
    r = client.post("/captures", json=VALID_PAYLOAD)
    assert r.status_code == 201
    data = r.json()
    assert data["url"] == VALID_PAYLOAD["url"]
    assert data["title"] == VALID_PAYLOAD["title"]
    assert data["label"] == "return"
    assert data["status"] == "saved"
    assert "id" in data


def test_create_capture_with_selected_text(client):
    r = client.post("/captures", json={
        "source_type": "passage",
        "selected_text": "Some interesting passage worth saving.",
        "label": "casual",
    })
    assert r.status_code == 201
    assert r.json()["label"] == "casual"


def test_create_capture_with_user_note_only(client):
    r = client.post("/captures", json={
        "source_type": "note",
        "user_note": "Remember to look into this later.",
        "label": "return",
    })
    assert r.status_code == 201


def test_create_capture_rejects_missing_content(client):
    """Must supply at least one of url, selected_text, or user_note."""
    r = client.post("/captures", json={
        "source_type": "article",
        "title": "Title only, no content",
        "label": "return",
    })
    assert r.status_code == 422


def test_create_capture_rejects_missing_label(client):
    r = client.post("/captures", json={
        "source_type": "article",
        "url": "https://example.com",
    })
    assert r.status_code == 422


def test_create_capture_rejects_invalid_source_type(client):
    r = client.post("/captures", json={
        "source_type": "pdf",
        "url": "https://example.com",
        "label": "return",
    })
    assert r.status_code == 422


def test_list_captures_returns_created(client):
    client.post("/captures", json=VALID_PAYLOAD)
    client.post("/captures", json={**VALID_PAYLOAD, "url": "https://example.com/2"})
    r = client.get("/captures")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_list_captures_empty(client):
    r = client.get("/captures")
    assert r.status_code == 200
    assert r.json() == []


def test_get_capture_by_id(client):
    created = client.post("/captures", json=VALID_PAYLOAD).json()
    r = client.get(f"/captures/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_capture_not_found(client):
    r = client.get("/captures/nonexistent-id")
    assert r.status_code == 404
