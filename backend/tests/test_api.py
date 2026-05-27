from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_ready_endpoint(client: TestClient) -> None:
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready"}


def test_bet_crud_and_bankroll_ledger(client: TestClient) -> None:
    # Fresh DB => empty state.
    res = client.get("/bets")
    assert res.status_code == 200
    assert res.json() == []

    # Create a bet.
    res = client.post(
        "/bets",
        json={
            "sport": "NBA",
            "bet_type": "moneyline",
            "event": "Lakers vs Celtics",
            "selection": "Lakers ML",
            "odds": 150,
            "stake": 100,
            "sportsbook": "DraftKings",
            "notes": "",
            "estimated_probability": 0.5,
        },
    )
    assert res.status_code == 201, res.text
    bet = res.json()
    assert bet["status"] == "pending"
    assert bet["potential_payout"] == 250.0  # 100 * (150/100 + 1)
    assert bet["expected_value"] is not None

    bet_id = bet["id"]

    # Bankroll snapshot reflects the stake deduction.
    res = client.get("/bets/bankroll/snapshot")
    assert res.status_code == 200
    snap = res.json()
    assert snap["initial_balance"] == 1000.0
    assert snap["current_balance"] == 900.0
    assert snap["total_wagered"] == 100.0
    assert snap["total_returned"] == 0.0
    assert len(snap["history"]) == 1

    # Mark won — bankroll goes up by potential_payout.
    res = client.patch(f"/bets/{bet_id}/status", json={"status": "won"})
    assert res.status_code == 200
    assert res.json()["status"] == "won"

    snap = client.get("/bets/bankroll/snapshot").json()
    assert snap["current_balance"] == 1150.0  # 900 + 250
    assert snap["total_returned"] == 250.0

    # Flip won -> lost — bankroll must fully reverse the win back out.
    res = client.patch(f"/bets/{bet_id}/status", json={"status": "lost"})
    assert res.status_code == 200
    snap = client.get("/bets/bankroll/snapshot").json()
    assert snap["current_balance"] == 900.0

    # Delete — bet disappears, bankroll returns to 1000.
    res = client.delete(f"/bets/{bet_id}")
    assert res.status_code == 204
    snap = client.get("/bets/bankroll/snapshot").json()
    assert snap["current_balance"] == 1000.0
    assert client.get("/bets").json() == []


def test_update_status_of_missing_bet_is_404(client: TestClient) -> None:
    res = client.patch("/bets/99999/status", json={"status": "won"})
    assert res.status_code == 404


def test_create_bet_rejects_bad_stake(client: TestClient) -> None:
    res = client.post(
        "/bets",
        json={
            "sport": "NBA",
            "bet_type": "moneyline",
            "event": "Lakers vs Celtics",
            "selection": "Lakers ML",
            "odds": 150,
            "stake": 0,  # Must be > 0.
            "sportsbook": "DraftKings",
        },
    )
    assert res.status_code == 422
