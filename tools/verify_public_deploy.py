#!/usr/bin/env python3
"""Verify a live OpenHUD AI deployment against a real public URL.

Run this after deploying to Render/Fly/Railway/VPS to prove the site, API,
accounts and security headers actually work over HTTPS. It exercises real
network requests — no mocks, no fabricated results.

Usage:
    python tools/verify_public_deploy.py --base-url https://openhud.onrender.com
    python tools/verify_public_deploy.py --base-url https://... --full
    OPENHUD_PUBLIC_URL=https://... python tools/verify_public_deploy.py

Exit code 0 only if every check passes; 1 on failure; 2 on bad invocation.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import sys
import urllib.error
import urllib.request

PAGES = ["/", "/features", "/how-it-works", "/pricing", "/help", "/privacy",
         "/download", "/changelog", "/login", "/register"]
ENDPOINTS = ["/health", "/ready", "/version", "/api/site/config", "/api/site/release"]

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def req(self, path: str, method: str = "GET", data: dict | None = None,
            headers: dict | None = None):
        body = json.dumps(data).encode() if data is not None else None
        h = {"Content-Type": "application/json", "Origin": self.base}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with self.op.open(r, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()
        except Exception as e:  # noqa: BLE001
            return 0, {}, str(e)

    def json(self, path: str):
        status, headers, text = self.req(path)
        try:
            return status, headers, json.loads(text or "{}")
        except json.JSONDecodeError:
            return status, headers, {}

    def cookie(self, name: str) -> str | None:
        for c in self.cj:
            if c.name == name:
                return c.value
        return None

    def csrf(self) -> str | None:
        _, _, body = self.json("/api/account/csrf")
        return body.get("csrf") or self.cookie("openhud_csrf")


def check_public(client: Client) -> None:
    for path in PAGES:
        status, headers, text = client.req(path)
        ok = status == 200 and "OpenHUD" in text
        record(ok, f"page {path}", f"HTTP {status}")

    for path in ENDPOINTS:
        status, _, _ = client.json(path)
        record(status == 200, f"endpoint {path}", f"HTTP {status}")

    status, _, cfg = client.json("/api/site/config")
    record(status == 200 and "donation_url" in cfg, "api /api/site/config", f"HTTP {status}")

    status, _, rel = client.json("/api/site/release")
    record(status == 200, "api /api/site/release", f"HTTP {status}")
    record("Unreleased" not in str(rel.get("notes", "")), "release notes not 'Unreleased'")


def check_security(client: Client) -> None:
    status, headers, _ = client.req("/")
    lh = {k.lower(): v for k, v in headers.items()}
    record(lh.get("x-content-type-options") == "nosniff", "header X-Content-Type-Options")
    record(lh.get("x-frame-options") == "DENY", "header X-Frame-Options")
    record("content-security-policy" in lh, "header Content-Security-Policy")
    record(lh.get("referrer-policy", "").startswith("strict-origin"), "header Referrer-Policy")
    # HTTPS deployment should advertise HSTS; plain HTTP must not.
    if client.base.startswith("https://"):
        record("max-age=" in lh.get("strict-transport-security", ""), "header HSTS (https)")
    record(lh.get("access-control-allow-origin") != "*", "CORS not wildcard")


def check_accounts(client: Client, full: bool) -> None:
    status, _, me = client.json("/api/account/me")
    record(status == 200 and "authenticated" in me, "/api/account/me reachable", f"HTTP {status}")
    record(me.get("authenticated") is False, "unauthenticated by default")

    if not full:
        return

    email = f"verify-{secrets.token_hex(4)}@example.com"
    pw = "Str0ng-Passw0rd!" + secrets.token_hex(3)
    csrf = client.csrf()
    status, _, text = client.req("/api/account/register", "POST",
                                 {"email": email, "password": pw, "name": "Verify", "csrf": csrf})
    record(status == 200, "register", f"HTTP {status}")

    status, _, me = client.json("/api/account/me")
    record(me.get("authenticated") is True, "session after register")

    client.req("/api/account/logout", "POST", {"csrf": client.cookie("openhud_csrf")})
    _, _, me = client.json("/api/account/me")
    record(me.get("authenticated") is False, "logout clears session")

    csrf = client.csrf()
    status, _, text = client.req("/api/account/login", "POST",
                                 {"email": email, "password": pw, "csrf": csrf})
    record(status == 200, "login", f"HTTP {status}")
    _, _, me = client.json("/api/account/me")
    record(me.get("authenticated") is True, "session after login")

    status, _, sess = client.json("/api/account/sessions")
    record(status == 200, "protected endpoint /api/account/sessions", f"HTTP {status}")

    status, _, text = client.req("/api/account/delete", "POST",
                                 {"csrf": client.cookie("openhud_csrf"), "password": pw,
                                  "confirm": "EXCLUIR"})
    record(status == 200, "delete test account", f"HTTP {status}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify a live OpenHUD AI deployment.")
    ap.add_argument("--base-url", default="",
                    help="Public base URL (or set OPENHUD_PUBLIC_URL)")
    ap.add_argument("--full", action="store_true",
                    help="Also run the register/login/session/delete flow (creates then deletes a test user)")
    args = ap.parse_args()

    import os
    base = (args.base_url or os.environ.get("OPENHUD_PUBLIC_URL", "")).strip()
    if not base:
        print("Informe --base-url https://... ou defina OPENHUD_PUBLIC_URL.")
        return 2

    print(f"== Verificando deploy público: {base} ==\n")
    client = Client(base)
    try:
        check_public(client)
        check_security(client)
        check_accounts(client, args.full)
    except Exception as e:  # noqa: BLE001
        record(False, "verificação", str(e))

    width = max(len(n) for _, n, _ in results)
    failures = 0
    for state, name, detail in results:
        if state == FAIL:
            failures += 1
        print(f"[{state}] {name.ljust(width)}  {detail}")
    print(f"\n{len(results) - failures}/{len(results)} verificações passaram.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
