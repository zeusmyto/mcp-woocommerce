"""MCP server that lets Claude (or any MCP client) answer questions about a WooCommerce shop.

Read-only by default. The only write tool (update_stock) refuses to run
unless WC_ALLOW_WRITE=true, and it reports the value before and after.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from functools import wraps

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .woo import WooClient, WooConfig, WooError, order_summary, product_summary, since

INSTRUCTIONS = """Tools for a WooCommerce shop: search products, read orders (without customer
personal data), sales summaries and low stock. Prices and totals are in the shop currency.
Ask the user before calling update_stock."""


def readable_errors(fn):
    """Send WooCommerce / validation errors to the client as clear tool errors."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (WooError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


def create_server(client: WooClient | None = None) -> MCPServer:
    server = MCPServer("woocommerce", instructions=INSTRUCTIONS)
    state = {"client": client}

    def woo() -> WooClient:
        if state["client"] is None:
            state["client"] = WooClient(WooConfig.from_env())
        return state["client"]

    @server.tool()
    @readable_errors
    def search_products(query: str, limit: int = 10) -> list[dict]:
        """Search products by name or SKU. Returns id, name, price, stock and sales."""
        items = woo().get("/products", search=query, per_page=min(max(limit, 1), 50))
        return [product_summary(p) for p in items]

    @server.tool()
    @readable_errors
    def get_product(product_id: int) -> dict:
        """Full details of one product, including its description."""
        p = woo().get(f"/products/{product_id}")
        return {**product_summary(p), "description": p.get("short_description") or p.get("description"),
                "permalink": p.get("permalink")}

    @server.tool()
    @readable_errors
    def list_orders(status: str = "any", days: int = 30, limit: int = 20) -> list[dict]:
        """Recent orders (no customer names or contact details). status: any, processing, completed, on-hold..."""
        params = {"after": since(days), "per_page": min(max(limit, 1), 100), "orderby": "date", "order": "desc"}
        if status != "any":
            params["status"] = status
        return [order_summary(o) for o in woo().get("/orders", **params)]

    @server.tool()
    @readable_errors
    def sales_summary(days: int = 30) -> dict:
        """Revenue, number of orders, average order and best sellers over the last N days
        (orders with status processing or completed)."""
        orders = [o for o in woo().get_all("/orders", after=since(days))
                  if o.get("status") in {"processing", "completed"}]
        revenue = sum((Decimal(o.get("total") or "0") for o in orders), Decimal("0"))
        best = Counter()
        for o in orders:
            for item in o.get("line_items", []):
                best[item.get("name")] += int(item.get("quantity") or 0)
        count = len(orders)
        return {
            "days": days,
            "orders": count,
            "revenue": str(revenue),
            "average_order": str((revenue / count).quantize(Decimal("0.01"))) if count else "0",
            "currency": orders[0].get("currency") if orders else None,
            "best_sellers": [{"name": n, "quantity": q} for n, q in best.most_common(5)],
        }

    @server.tool()
    @readable_errors
    def low_stock(threshold: int = 5) -> list[dict]:
        """Products whose managed stock is at or below the threshold, lowest first."""
        products = woo().get_all("/products", status="publish")
        low = [product_summary(p) for p in products
               if p.get("manage_stock") and p.get("stock_quantity") is not None
               and p["stock_quantity"] <= threshold]
        return sorted(low, key=lambda p: p["stock_quantity"])

    @server.tool()
    @readable_errors
    def update_stock(product_id: int, quantity: int) -> dict:
        """Set the stock quantity of a product. Requires WC_ALLOW_WRITE=true. Confirm with the user first."""
        if quantity < 0:
            raise ValueError("quantity must be >= 0")
        client = woo()
        before = client.get(f"/products/{product_id}").get("stock_quantity")
        after = client.put(f"/products/{product_id}", {"manage_stock": True, "stock_quantity": quantity})
        return {"id": product_id, "name": after.get("name"),
                "stock_before": before, "stock_after": after.get("stock_quantity")}

    return server


def main() -> None:
    create_server().run()  # stdio transport, for Claude Desktop / Claude Code


if __name__ == "__main__":
    main()
