#!/usr/bin/env python3
"""Send a signed Slack-style request to our Events endpoint.

Slack signs every request with the app's Signing Secret. This script does the
same, so you can verify the endpoint yourself before (or instead of) pressing
"Verify URL" in the Slack admin UI.

Usage:
    python scripts/check_slack_events.py                    # challenge, localhost
    python scripts/check_slack_events.py --url https://...  # challenge, public URL
    python scripts/check_slack_events.py --all              # every check

The secret is read from .env (SLACK_SIGNING_SECRET) and never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8000/slack/events"
# Slack posts with this agent; ngrok-free lets it through its interstitial.
SLACK_UA = "Slackbot 1.0 (+https://api.slack.com/robots)"


def read_secret() -> str:
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("ERROR: .env not found")
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("SLACK_SIGNING_SECRET="):
            secret = line.split("=", 1)[1].strip()
            if not secret:
                sys.exit("ERROR: SLACK_SIGNING_SECRET is empty in .env")
            return secret
    sys.exit("ERROR: SLACK_SIGNING_SECRET missing from .env")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b":".join([b"v0", timestamp.encode(), body])
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def post(url: str, payload: dict, secret: str, *, timestamp: str | None = None,
         signature: str | None = None) -> tuple[int, str]:
    body = json.dumps(payload).encode()
    ts = timestamp or str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": SLACK_UA,
        "x-slack-request-timestamp": ts,
        "x-slack-signature": signature if signature is not None else sign(secret, ts, body),
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode()[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()[:200]
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        return 0, f"{type(exc).__name__}: {exc}"


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}\n      {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="endpoint to call")
    parser.add_argument("--all", action="store_true", help="run negative checks too")
    args = parser.parse_args()

    secret = read_secret()
    print(f"endpoint: {args.url}")
    print(f"secret:   {len(secret)} chars (not printed)\n")

    failures = 0

    status, body = post(args.url, {"type": "url_verification", "challenge": "self-check"},
                        secret)
    failures += not check(
        "challenge with a valid signature (this is what Slack Verify URL does)",
        status == 200 and '"challenge":"self-check"' in body.replace(" ", ""),
        f"HTTP {status} {body}",
    )

    if args.all:
        status, body = post(args.url, {"type": "url_verification", "challenge": "x"},
                            secret, signature="v0=" + "0" * 64)
        failures += not check("wrong signature is rejected", status == 401, f"HTTP {status} {body}")

        stale = str(int(time.time()) - 3600)
        status, body = post(args.url, {"type": "url_verification", "challenge": "x"},
                            secret, timestamp=stale)
        failures += not check("stale timestamp is rejected", status == 401, f"HTTP {status} {body}")

        status, body = post(args.url, {
            "type": "event_callback", "event_id": "self-check-event",
            "event": {"type": "message", "channel": "C_UNKNOWN",
                      "thread_ts": "1.000", "ts": "2.000", "text": "hello"},
        }, secret)
        failures += not check(
            "event from an unknown thread is accepted and ignored",
            status == 200 and "unknown-thread" in body,
            f"HTTP {status} {body}",
        )

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
