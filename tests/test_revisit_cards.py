"""Tests for Revisit Card creation and retrieval."""

import pytest
from app.services import capture_store, embeddings, clustering
from app.schemas.capture import CaptureCreate, SourceType, CaptureLabel


def _make_capture(client, **overrides):
    payload = {
        "source_type": "article",
        "url": "https://example.com/test",
        "title": "Test",
        "label": "return",
        **overrides,
    }
    r = client.post("/captures", json=payload)
    assert r.status_code == 201
    return r.json()


def test_create_individual_card_rule_based(client):
    cap = _make_capture(client, url="https://example.com/ml")
    r = client.post(f"/captures/{cap['id']}/revisit-card")
    assert r.status_code == 201
    card = r.json()
    assert card["card_type"] == "individual"
    assert card["generation_method"] == "rule_based"
    assert card["capture_id"] == cap["id"]
    assert card["cluster_id"] is None
    assert card["title"]
    assert card["why_saved"]
    assert card["next_action"]


def test_create_card_missing_capture(client):
    r = client.post("/captures/no-such-id/revisit-card")
    assert r.status_code == 404


def test_list_revisit_cards_empty(client):
    r = client.get("/revisit-cards")
    assert r.status_code == 200
    assert r.json() == []


def test_list_revisit_cards_returns_created(client):
    cap = _make_capture(client)
    client.post(f"/captures/{cap['id']}/revisit-card")
    r = client.get("/revisit-cards")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_card_by_id(client):
    cap = _make_capture(client)
    created = client.post(f"/captures/{cap['id']}/revisit-card").json()
    r = client.get(f"/revisit-cards/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_card_not_found(client):
    r = client.get("/revisit-cards/no-such-id")
    assert r.status_code == 404


def test_create_cluster_card_rule_based(client, db):
    """End-to-end: two captures → embed → cluster → cluster card.

    Uses fake embeddings (OPENAI_API_KEY absent). Both captures receive
    identical extracted_text so the fake embedding is bit-for-bit identical
    → cosine similarity = 1.0 → they land in the same cluster.
    """
    shared_text = "Attention mechanisms in transformer neural networks"

    # Create and embed two captures directly through the service layer so
    # extracted_text can be set without a real HTTP fetch.
    c1 = capture_store.create_capture(db, CaptureCreate(
        source_type=SourceType.passage,
        selected_text=shared_text,
        label=CaptureLabel.return_,
        title="Attention A",
    ))
    c2 = capture_store.create_capture(db, CaptureCreate(
        source_type=SourceType.passage,
        selected_text=shared_text,
        label=CaptureLabel.return_,
        title="Attention B",
    ))
    capture_store.update_extraction(db, c1.id, extracted_text=shared_text,
                                    status="extracted", extraction_error=None)
    capture_store.update_extraction(db, c2.id, extracted_text=shared_text,
                                    status="extracted", extraction_error=None)
    embeddings.create_embedding_for_capture(db, c1.id)
    embeddings.create_embedding_for_capture(db, c2.id)

    summary = clustering.run_clustering(db)
    assert summary.captures_considered == 2
    assert summary.clusters_created == 1  # both go into the same cluster

    clusters = client.get("/clusters").json()
    assert len(clusters) == 1
    cluster_id = clusters[0]["id"]

    r = client.post(f"/clusters/{cluster_id}/revisit-card")
    assert r.status_code == 201
    card = r.json()
    assert card["card_type"] == "cluster"
    assert card["cluster_id"] == cluster_id
    assert card["generation_method"] == "rule_based"


def test_create_cluster_card_missing_cluster(client):
    r = client.post("/clusters/no-such-id/revisit-card")
    assert r.status_code == 404
