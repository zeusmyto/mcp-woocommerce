"""Tests against a fake WooCommerce API: no shop or credentials needed."""
import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_woocommerce.server import create_server
from mcp_woocommerce.woo import WooClient, WooConfig, WooError, order_summary

PRODUCTS = [
    {"id": 1, "name": "RTX 4070 Super", "sku": "GPU-4070S", "price": "599.00", "status": "publish",
     "stock_status": "instock", "manage_stock": True, "stock_quantity": 3, "total_sales": 41,
     "categories": [{"name": "Cartes graphiques"}], "short_description": "12 GB GDDR6X"},
    {"id": 2, "name": "Ryzen 7 7800X3D", "sku": "CPU-7800X3D", "price": "379.00", "status": "publish",
     "stock_status": "instock", "manage_stock": True, "stock_quantity": 12, "total_sales": 77,
     "categories": [{"name": "Processeurs"}]},
    {"id": 3, "name": "PC Gamer Zeus", "sku": "", "price": "1890.00", "status": "publish",
     "stock_status": "onbackorder", "manage_stock": True, "stock_quantity": 0, "total_sales": 9,
     "categories": [{"name": "PC"}]},
]

ORDERS = [
    {"id": 101, "date_created": "2026-11-01T10:00:00", "status": "completed", "total": "599.00", "currency": "CHF",
     "billing": {"first_name": "Anna", "email": "anna@example.com", "phone": "+41...", "country": "CH"},
     "line_items": [{"name": "RTX 4070 Super", "quantity": 1}]},
    {"id": 102, "date_created": "2026-11-03T12:00:00", "status": "processing", "total": "758.00", "currency": "CHF",
     "billing": {"first_name": "Marc", "email": "marc@example.com", "country": "FR"},
     "line_items": [{"name": "Ryzen 7 7800X3D", "quantity": 2}]},
    {"id": 103, "date_created": "2026-11-04T09:00:00", "status": "cancelled", "total": "1890.00", "currency": "CHF",
     "billing": {"country": "CH"}, "line_items": [{"name": "PC Gamer Zeus", "quantity": 1}]},
]


class FakeResponse:
    def __init__(self, status, data, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    """Routes requests like the WooCommerce REST API would."""

    def __init__(self):
        self.auth = None
        self.calls = []
        self.products = {p["id"]: dict(p) for p in PRODUCTS}

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url.split("/wp-json/wc/v3", 1)[1]
        self.calls.append((method, path, params, json))
        if method == "GET" and path == "/products":
            items = list(self.products.values())
            if params and params.get("search"):
                items = [p for p in items if params["search"].lower() in p["name"].lower()]
            return FakeResponse(200, items, {"X-WP-TotalPages": "1"})
        if path.startswith("/products/"):
            pid = int(path.rsplit("/", 1)[1])
            if pid not in self.products:
                return FakeResponse(404, {"message": "Invalid ID."})
            if method == "PUT":
                self.products[pid].update(json)
            return FakeResponse(200, self.products[pid])
        if method == "GET" and path == "/orders":
            items = ORDERS
            if params and params.get("status"):
                items = [o for o in items if o["status"] == params["status"]]
            return FakeResponse(200, items, {"X-WP-TotalPages": "1"})
        return FakeResponse(404, {"message": "No route"})


def make(allow_write=False):
    session = FakeSession()
    client = WooClient(WooConfig("https://shop.example", "ck", "cs", allow_write=allow_write), session=session)
    return create_server(client), session


def call(server, name, **args):
    try:
        result = asyncio.run(server.call_tool(name, args))
    except ToolError as exc:
        raise RuntimeError(str(exc)) from exc
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    data = result.structured_content
    if data is None:
        return json.loads(result.content[0].text)
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


def test_lists_all_tools():
    server, _ = make()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"search_products", "get_product", "list_orders", "sales_summary", "low_stock", "update_stock"}


def test_search_products():
    server, session = make()
    found = call(server, "search_products", query="ryzen")
    assert [p["name"] for p in found] == ["Ryzen 7 7800X3D"]
    assert session.auth == ("ck", "cs")


def test_get_product_includes_description():
    server, _ = make()
    p = call(server, "get_product", product_id=1)
    assert p["description"] == "12 GB GDDR6X" and p["categories"] == ["Cartes graphiques"]


def test_orders_have_no_personal_data():
    server, _ = make()
    orders = call(server, "list_orders")
    text = json.dumps(orders)
    assert "anna@example.com" not in text and "Anna" not in text and "+41" not in text
    assert orders[0]["country"] == "CH"


def test_sales_summary_ignores_cancelled_orders():
    server, _ = make()
    s = call(server, "sales_summary", days=30)
    assert s["orders"] == 2 and s["revenue"] == "1357.00" and s["average_order"] == "678.50"
    assert s["best_sellers"][0] == {"name": "Ryzen 7 7800X3D", "quantity": 2}


def test_low_stock_sorted():
    server, _ = make()
    low = call(server, "low_stock", threshold=5)
    assert [p["id"] for p in low] == [3, 1]


def test_update_stock_is_blocked_by_default():
    server, session = make(allow_write=False)
    with pytest.raises(RuntimeError, match="Write access is disabled"):
        call(server, "update_stock", product_id=1, quantity=10)
    assert not any(c[0] == "PUT" for c in session.calls)


def test_update_stock_when_allowed():
    server, _ = make(allow_write=True)
    r = call(server, "update_stock", product_id=1, quantity=10)
    assert r == {"id": 1, "name": "RTX 4070 Super", "stock_before": 3, "stock_after": 10}


def test_api_errors_are_readable():
    server, _ = make()
    with pytest.raises(RuntimeError, match="404: Invalid ID"):
        call(server, "get_product", product_id=999)


def test_order_summary_shape():
    assert set(order_summary(ORDERS[0])) == {"id", "date", "status", "total", "currency", "country", "items"}


def test_config_requires_env(monkeypatch):
    for v in ("WC_URL", "WC_KEY", "WC_SECRET"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(WooError, match="WC_URL"):
        WooConfig.from_env()
