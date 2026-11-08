"""Minimal WooCommerce REST API client (v3)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


class WooError(RuntimeError):
    pass


@dataclass
class WooConfig:
    url: str
    key: str
    secret: str
    allow_write: bool = False
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "WooConfig":
        missing = [v for v in ("WC_URL", "WC_KEY", "WC_SECRET") if not os.getenv(v)]
        if missing:
            raise WooError(f"Missing environment variables: {', '.join(missing)}")
        return cls(
            url=os.environ["WC_URL"].rstrip("/"),
            key=os.environ["WC_KEY"],
            secret=os.environ["WC_SECRET"],
            allow_write=os.getenv("WC_ALLOW_WRITE", "false").lower() in {"1", "true", "yes"},
        )


class WooClient:
    def __init__(self, config: WooConfig, session: requests.Session | None = None):
        self.config = config
        self.base = f"{config.url}/wp-json/wc/v3"
        self.session = session or requests.Session()
        self.session.auth = (config.key, config.secret)

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        r = self.session.request(method, f"{self.base}{path}", timeout=self.config.timeout, **kw)
        if r.status_code >= 400:
            try:
                message = r.json().get("message", r.text)
            except ValueError:
                message = r.text
            raise WooError(f"WooCommerce {r.status_code}: {message}")
        return r

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params=params).json()

    def get_all(self, path: str, max_pages: int = 10, **params) -> list[dict]:
        """Follow WooCommerce pagination (X-WP-TotalPages)."""
        items: list[dict] = []
        page = 1
        while page <= max_pages:
            r = self._request("GET", path, params={**params, "per_page": 100, "page": page})
            items.extend(r.json())
            total = int(r.headers.get("X-WP-TotalPages", "1"))
            if page >= total:
                break
            page += 1
        return items

    def put(self, path: str, body: dict) -> Any:
        if not self.config.allow_write:
            raise WooError("Write access is disabled. Set WC_ALLOW_WRITE=true to allow changes.")
        return self._request("PUT", path, json=body).json()


# --- shaping helpers: keep answers short and free of customer personal data ---

def product_summary(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "sku": p.get("sku") or None,
        "price": p.get("price"),
        "status": p.get("status"),
        "stock_status": p.get("stock_status"),
        "stock_quantity": p.get("stock_quantity"),
        "total_sales": p.get("total_sales"),
        "categories": [c.get("name") for c in p.get("categories", [])],
    }


def order_summary(o: dict) -> dict:
    # No names, emails, phones or addresses: only what is needed for business questions.
    return {
        "id": o.get("id"),
        "date": o.get("date_created"),
        "status": o.get("status"),
        "total": o.get("total"),
        "currency": o.get("currency"),
        "country": (o.get("billing") or {}).get("country"),
        "items": [{"name": i.get("name"), "quantity": i.get("quantity")} for i in o.get("line_items", [])],
    }


def since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
