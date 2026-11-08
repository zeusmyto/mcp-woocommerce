# mcp-woocommerce

![tests](https://github.com/zeusmyto/mcp-woocommerce/actions/workflows/ci.yml/badge.svg)

**An MCP server that connects Claude to a WooCommerce shop.** The shop owner asks questions in plain language, and Claude calls the shop's REST API to answer:

> *"What did we sell this month, and which products are about to run out?"*
> → `sales_summary(days=30)` + `low_stock(threshold=5)` → a short answer with the figures.

Works with Claude Desktop, Claude Code and any MCP client.

## Tools

| Tool | What it does |
|---|---|
| `search_products(query)` | Find products by name or SKU: price, stock, sales |
| `get_product(product_id)` | Details and description of one product |
| `list_orders(status, days)` | Recent orders, **without customer names, emails, phones or addresses** |
| `sales_summary(days)` | Revenue, number of orders, average order, best sellers (cancelled orders excluded) |
| `low_stock(threshold)` | Products at or below a stock level, lowest first |
| `update_stock(product_id, quantity)` | Change stock. **Disabled unless `WC_ALLOW_WRITE=true`**; returns before/after |

## Safe by default

- **Read-only** unless the owner explicitly enables writes.
- **No personal data sent to the model:** order tools strip customer identity and contact details; only country, items and totals are returned.
- **Least privilege:** create the WooCommerce API key with *Read* permission. Use *Read/Write* only if you enable `update_stock`.
- **Readable errors:** WooCommerce errors (wrong id, bad key) come back as clear tool errors instead of crashes.

## Setup

1. In WordPress: *WooCommerce → Settings → Advanced → REST API → Add key* (permission: Read).
2. Install:

```bash
pip install git+https://github.com/zeusmyto/mcp-woocommerce
```

3. Add it to Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "woocommerce": {
      "command": "mcp-woocommerce",
      "env": {
        "WC_URL": "https://your-shop.example",
        "WC_KEY": "ck_...",
        "WC_SECRET": "cs_..."
      }
    }
  }
}
```

Or with Claude Code:

```bash
claude mcp add woocommerce --env WC_URL=https://your-shop.example --env WC_KEY=ck_... --env WC_SECRET=cs_... -- mcp-woocommerce
```

## Development

```bash
pip install -e . pytest
python -m pytest -q
```

The tests run against a fake WooCommerce API (no shop or credentials needed) and check, among other things, that no customer personal data ever reaches the model and that writes are blocked by default.

Built on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (v2).

---

Built by [Adel Touhami](https://www.linkedin.com/in/adel-touhami-b35a352a) with Claude Code, from 15 years of building WooCommerce shops. MIT license.
