"""Post call webhook: emails Tony a summary of every receptionist call.

ElevenLabs sends a `post_call_transcription` event after each call. This
server verifies the signature, then emails the summary and transcript to
tcantave@localflyerads.com through Resend.

Env vars:
    ELEVENLABS_WEBHOOK_SECRET  from ElevenLabs > Agents > Settings > Webhooks
    RESEND_API_KEY             Resend API key (localflyerads.com verified)
    NOTIFY_TO                  defaults to tcantave@localflyerads.com
    NOTIFY_FROM                defaults to receptionist@localflyerads.com
    PORT                       defaults to 8080

Run:  python receptionist/webhook.py   (deploy on Railway next to the backend)
Standard library only.
"""

import hashlib
import hmac
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")
RESEND_KEY = os.environ.get("RESEND_API_KEY", "")
NOTIFY_TO = os.environ.get("NOTIFY_TO", "tcantave@localflyerads.com")
NOTIFY_FROM = os.environ.get("NOTIFY_FROM", "receptionist@localflyerads.com")
MAX_SKEW = 30 * 60  # reject events older than 30 minutes


def valid_signature(header: str, body: bytes) -> bool:
    """Header format: t=<unix>,v0=<hex hmac sha256 of 't.body'>."""
    if not SECRET or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v0")
    if not ts or not sig or abs(time.time() - int(ts)) > MAX_SKEW:
        return False
    expected = hmac.new(
        SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


def build_email(data: dict) -> tuple[str, str]:
    analysis = data.get("analysis") or {}
    summary = analysis.get("transcript_summary") or "No summary available."
    lines = [
        f"{'Caller' if t.get('role') == 'user' else 'Receptionist'}: {t.get('message', '')}"
        for t in data.get("transcript", [])
        if t.get("message")
    ]
    subject = "New call for Local Flyer Ads CT"
    text = (
        f"Summary:\n{summary}\n\n"
        f"Conversation ID: {data.get('conversation_id', '')}\n\n"
        "Transcript:\n" + "\n".join(lines)
    )
    return subject, text


def send_email(subject: str, text: str) -> None:
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(
            {"from": NOTIFY_FROM, "to": [NOTIFY_TO], "subject": subject, "text": text}
        ).encode(),
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # health check
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not valid_signature(self.headers.get("ElevenLabs-Signature", ""), body):
            self.send_response(401)
            self.end_headers()
            return

        event = json.loads(body or b"{}")
        if event.get("type") == "post_call_transcription":
            try:
                send_email(*build_email(event.get("data", {})))
            except Exception as exc:  # keep 200 so ElevenLabs does not retry forever
                print(f"email failed: {exc}")

        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Receptionist webhook listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
