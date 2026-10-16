"""The few Stripe API calls host payouts need (Stripe Connect Express).

Hosts get an Express connected account; Stripe hosts the onboarding where
they add their bank account, and the owner sends each month's earnings as a
transfer. Calls go straight to Stripe's REST API with the secret key in
STRIPE_SECRET_KEY."""

import httpx

from .config import settings

API = "https://api.stripe.com/v1"


class StripeError(Exception):
    """Stripe refused a request; the message is Stripe's, safe to show."""


def configured() -> bool:
    return bool(settings.stripe_secret_key)


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: {"a": {"b": 1}} -> a[b]=1."""
    out = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            out += _flatten(value, name)
        elif isinstance(value, bool):
            out.append((name, "true" if value else "false"))
        elif value is not None:
            out.append((name, str(value)))
    return out


def _request(method: str, path: str, data: dict | None = None, idempotency_key: str | None = None) -> dict:
    if not configured():
        raise StripeError("Stripe payouts aren't set up on this server (STRIPE_SECRET_KEY is missing).")
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    try:
        r = httpx.request(method, API + path, data=_flatten(data or {}), headers=headers,
                          auth=(settings.stripe_secret_key, ""), timeout=20)
    except httpx.HTTPError as e:
        raise StripeError(f"Couldn't reach Stripe: {e}") from e
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        raise StripeError((body.get("error") or {}).get("message") or f"Stripe error {r.status_code}")
    return body


def create_express_account(email: str | None, business_name: str, host_id: str) -> str:
    account = _request("POST", "/accounts", {
        "type": "express",
        "country": "US",
        "email": email,
        "business_profile": {"name": business_name},
        "capabilities": {"transfers": {"requested": True}},
        "metadata": {"host_id": host_id},
    }, idempotency_key=f"host-account-{host_id}")
    return account["id"]


def onboarding_link(account_id: str, refresh_url: str, return_url: str) -> str:
    link = _request("POST", "/account_links", {
        "account": account_id, "refresh_url": refresh_url, "return_url": return_url,
        "type": "account_onboarding",
    })
    return link["url"]


def payouts_ready(account_id: str) -> bool:
    account = _request("GET", f"/accounts/{account_id}")
    transfers = ((account.get("capabilities") or {}).get("transfers"))
    return transfers == "active" and bool(account.get("payouts_enabled"))


def create_transfer(amount: int, currency: str, destination: str, description: str,
                    metadata: dict, idempotency_key: str) -> str:
    transfer = _request("POST", "/transfers", {
        "amount": amount, "currency": currency.lower(), "destination": destination,
        "description": description, "metadata": metadata,
    }, idempotency_key=idempotency_key)
    return transfer["id"]
