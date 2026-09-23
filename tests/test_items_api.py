"""The table contract: search, pagination, CRUD and validation."""
from __future__ import annotations


def test_list_returns_rows_and_the_total_the_pager_needs(client, auth):
    page = client.get("/api/items?per_page=3", headers=auth).json()
    assert len(page["rows"]) == 3
    assert page["total"] == 8
    assert page["pages"] == 3


def test_search_matches_arabic_name_and_category(client, auth):
    by_category = client.get("/api/items?q=سلامة", headers=auth).json()
    assert by_category["total"] == 2
    by_name = client.get("/api/items?q=أسمنت", headers=auth).json()
    assert [r["name"] for r in by_name["rows"]] == ["أسمنت بورتلاندي"]


def test_last_page_and_out_of_range_page(client, auth):
    last = client.get("/api/items?per_page=3&page=3", headers=auth).json()
    assert len(last["rows"]) == 2
    beyond = client.get("/api/items?per_page=3&page=9", headers=auth).json()
    assert beyond["rows"] == [] and beyond["total"] == 8


def test_per_page_is_capped(client, auth):
    page = client.get("/api/items?per_page=100000", headers=auth).json()
    assert page["pages"] == 1 and len(page["rows"]) == 8


def test_create_update_delete(client, auth):
    created = client.post("/api/items", headers=auth,
                          json={"name": "مسمار 10 سم", "category": "مواد بناء", "quantity": 500})
    assert created.status_code == 201
    item_id = created.json()["item_id"]

    updated = client.put(f"/api/items/{item_id}", headers=auth,
                         json={"name": "مسمار 10 سم", "quantity": 12, "status": "low"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "low"

    assert client.delete(f"/api/items/{item_id}", headers=auth).status_code == 204
    assert client.delete(f"/api/items/{item_id}", headers=auth).status_code == 404


def test_validation_rejects_negative_quantity_and_unknown_status(client, auth):
    assert client.post("/api/items", headers=auth,
                       json={"name": "x", "quantity": -1}).status_code == 422
    assert client.post("/api/items", headers=auth,
                       json={"name": "x", "status": "deleted"}).status_code == 422
    assert client.post("/api/items", headers=auth, json={"name": ""}).status_code == 422


def test_search_input_is_a_parameter_not_sql(client, auth):
    page = client.get("/api/items?q=' OR 1=1 --", headers=auth).json()
    assert page["total"] == 0
