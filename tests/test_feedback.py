"""Tests for feedback submission and summary."""


def _make_card(client) -> dict:
    cap = client.post("/captures", json={
        "source_type": "note",
        "user_note": "Something worth revisiting",
        "label": "return",
    }).json()
    return client.post(f"/captures/{cap['id']}/revisit-card").json()


def test_post_feedback_opened(client):
    card = _make_card(client)
    r = client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "opened"})
    assert r.status_code == 201
    data = r.json()
    assert data["action"] == "opened"
    assert data["revisit_card_id"] == card["id"]
    assert data["rating"] is None


def test_post_feedback_useful_with_rating(client):
    card = _make_card(client)
    r = client.post(f"/revisit-cards/{card['id']}/feedback",
                    json={"action": "useful", "rating": 5})
    assert r.status_code == 201
    assert r.json()["rating"] == 5


def test_post_feedback_invalid_action(client):
    card = _make_card(client)
    r = client.post(f"/revisit-cards/{card['id']}/feedback",
                    json={"action": "totally_invalid"})
    assert r.status_code == 422


def test_post_feedback_invalid_rating_out_of_range(client):
    card = _make_card(client)
    r = client.post(f"/revisit-cards/{card['id']}/feedback",
                    json={"action": "useful", "rating": 10})
    assert r.status_code == 422


def test_post_feedback_invalid_rating_zero(client):
    card = _make_card(client)
    r = client.post(f"/revisit-cards/{card['id']}/feedback",
                    json={"action": "useful", "rating": 0})
    assert r.status_code == 422


def test_post_feedback_missing_card(client):
    r = client.post("/revisit-cards/no-such-id/feedback", json={"action": "opened"})
    assert r.status_code == 404


def test_list_feedback_for_card(client):
    card = _make_card(client)
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "opened"})
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "useful"})
    r = client.get(f"/revisit-cards/{card['id']}/feedback")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_feedback_summary_useful_rate(client):
    card = _make_card(client)
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "useful"})
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "useful"})
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "not_useful"})

    r = client.get("/feedback/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total_feedback_events"] == 3
    # useful_rate = 2 useful / (2 useful + 1 not_useful) = 2/3
    assert abs(data["useful_rate"] - 2 / 3) < 0.001


def test_feedback_summary_no_feedback(client):
    r = client.get("/feedback/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total_feedback_events"] == 0
    assert data["useful_rate"] is None
    assert data["dismiss_rate"] is None
    assert data["average_rating"] is None


def test_feedback_summary_dismiss_rate(client):
    card = _make_card(client)
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "dismissed"})
    client.post(f"/revisit-cards/{card['id']}/feedback", json={"action": "opened"})

    r = client.get("/feedback/summary")
    data = r.json()
    assert data["total_feedback_events"] == 2
    assert abs(data["dismiss_rate"] - 0.5) < 0.001
