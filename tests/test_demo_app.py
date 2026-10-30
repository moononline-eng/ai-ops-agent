"""Tests for the demo app. Agent PRs must keep these green.

The planted bugs are deliberately *not* covered here, as in many real apps.
A good agent PR adds a test for the bug it fixes.
"""

from fastapi.testclient import TestClient

from demo_app.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_order_with_discount():
    assert client.get("/orders/1").json() == {"id": 1, "final_total": 108.0}


def test_unknown_order_is_404():
    assert client.get("/orders/99").status_code == 404


def test_search_finds_products():
    assert client.get("/search", params={"q": "product-1"}).json()["count"] > 0
