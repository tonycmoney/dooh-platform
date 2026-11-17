"""Sends email through Resend's HTTPS API (Railway's Hobby plan blocks SMTP).

Without RESEND_API_KEY and ALERT_EMAIL_TO, emails are only logged, so alerts
and reports still work locally and show on the dashboard.
"""

import logging

import httpx

from .config import settings

log = logging.getLogger("dooh.email")

RESEND_URL = "https://api.resend.com/emails"


def email_configured() -> bool:
    return bool(settings.resend_api_key and settings.alert_email_to)


def recipients() -> list[str]:
    return [a.strip() for a in settings.alert_email_to.split(",") if a.strip()]


def send_email(subject: str, text: str, html: str | None = None, to: list[str] | None = None,
               reply_to: str | None = None, sender: str | None = None) -> bool:
    """Returns True if the email was accepted for delivery. Goes to the owner
    (ALERT_EMAIL_TO) unless `to` is given."""
    if not (settings.resend_api_key and (to or settings.alert_email_to)):
        log.info("Email not configured; would send: %s", subject)
        return False
    body = {"from": sender or settings.alert_email_from, "to": to or recipients(), "subject": subject, "text": text}
    if reply_to:
        body["reply_to"] = reply_to
    if html:
        body["html"] = html
    try:
        res = httpx.post(RESEND_URL, json=body, timeout=20,
                         headers={"Authorization": f"Bearer {settings.resend_api_key}"})
    except httpx.HTTPError as e:
        log.warning("Email '%s' failed: %s", subject, e.__class__.__name__)
        return False
    if res.status_code >= 300:
        log.warning("Email '%s' refused [%s]: %s", subject, res.status_code, res.text[:300])
        return False
    return True


def dashboard_link(path: str = "") -> str:
    return f"{settings.public_url.rstrip('/')}{path}" if settings.public_url else ""
