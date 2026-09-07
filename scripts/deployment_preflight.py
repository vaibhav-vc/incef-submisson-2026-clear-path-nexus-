"""Read-only production Compose checks. Never print configuration or secrets.

Run: python scripts/deployment_preflight.py --env-file .env
Requires Docker Compose 2.24.4+. Checks configuration, not a running deployment.
Use --url https://your-domain to additionally probe actual readiness over HTTPS.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = ("replace_", "your_", "your-", "example", "change_me", "changeme")


class NoReadinessRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A login redirect, another host, or HTTPS downgrade is not readiness.
        return None


def urlopen(request: Request, timeout: int):
    return build_opener(NoReadinessRedirect()).open(request, timeout=timeout)


def placeholder(value: str) -> bool:
    return not value.strip() or any(token in value.lower() for token in PLACEHOLDERS)


def https_origin(value: str) -> bool:
    try:
        url = urlsplit(value)
        return bool(url.scheme == "https" and url.hostname and not url.username
                    and not url.password and url.path in ("", "/")
                    and not url.query and not url.fragment
                    and not re.search(r"[\s;{}*]", value))
    except ValueError:
        return False


def is_public_supabase_key(value: str) -> bool:
    if placeholder(value):
        return False
    if value.startswith("sb_publishable_"):
        return len(value) > len("sb_publishable_") + 10
    try:
        segments = value.split(".")
        if len(segments) != 3:
            return False
        claims = json.loads(base64.urlsafe_b64decode(segments[1] + "=" * (-len(segments[1]) % 4)))
        return isinstance(claims, dict) and claims.get("role") == "anon"
    except (ValueError, UnicodeDecodeError):
        return False


def validate(model: dict) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def fail(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    services = model.get("services", {})
    backend = services.get("backend", {}).get("environment", {})
    for name in ("backend", "postgres", "redis", "frontend", "live-ingestor", "https"):
        if name not in services:
            fail("MISSING_SERVICE", f"Required service {name} is absent.")
    for name in ("backend", "postgres", "redis", "frontend"):
        if services.get(name, {}).get("ports"):
            fail("EXPOSED_INTERNAL_PORT", f"{name} must not publish host ports in production.")
    for name in ("backend", "live-ingestor", "train-synchronizer"):
        if name not in services:
            continue
        env = services[name].get("environment", {})
        if env.get("ENVIRONMENT") != "production":
            fail("NON_PRODUCTION_SERVICE", f"{name} must use production validation.")
        for flag in ("AUTH_DISABLED", "DEMO_DATA_ENABLED", "DEBUG"):
            if str(env.get(flag, "false")).lower() != "false":
                fail("UNSAFE_FLAG", f"{name}: {flag} must be false.")
        for key in ("SECRET_KEY", "EVIDENCE_SIGNING_KEY", "POSTGRES_PASSWORD"):
            value = str(env.get(key) or "")
            if placeholder(value) or len(value) < (16 if key == "POSTGRES_PASSWORD" else 32):
                fail("UNSAFE_SECRET", f"{name}: {key} requires a strong non-placeholder value.")
        if env.get("SECRET_KEY") == env.get("EVIDENCE_SIGNING_KEY"):
            fail("REUSED_SIGNING_SECRET", f"{name}: evidence signing requires a separate secret.")
        try:
            retired = json.loads(str(env.get("EVIDENCE_VERIFICATION_KEYS", "{}")))
            if not isinstance(retired, dict) or any(
                not isinstance(key, str) or not key.strip() or not isinstance(value, str)
                or placeholder(value) or len(value) < 32 for key, value in retired.items()
            ):
                raise ValueError
            if env.get("EVIDENCE_SIGNING_KEY_ID") in retired:
                raise ValueError
        except (TypeError, ValueError):
            fail("INVALID_RETIRED_KEYS", f"{name}: retained verification keys must be valid secrets under retired key IDs only.")
        if name != "backend":
            for key in ("EVIDENCE_SIGNING_KEY", "EVIDENCE_SIGNING_KEY_ID", "POSTGRES_PASSWORD"):
                if env.get(key) != backend.get(key):
                    fail("WORKER_CONFIG_MISMATCH", f"{name}: {key} differs from backend.")
    supabase = str(backend.get("SUPABASE_URL") or "")
    if not https_origin(supabase) or placeholder(supabase):
        fail("INVALID_SUPABASE_ORIGIN", "SUPABASE_URL requires a real HTTPS origin.")
    args = services.get("frontend", {}).get("build", {}).get("args", {})
    if args.get("VITE_SUPABASE_URL", "").rstrip("/") != supabase.rstrip("/"):
        fail("AUTH_PROJECT_MISMATCH", "Frontend and backend must use the same Supabase project.")
    if not is_public_supabase_key(str(args.get("VITE_SUPABASE_ANON_KEY") or "")):
        fail("INVALID_PUBLIC_KEY", "Frontend requires a publishable or legacy anon key, never a secret/service-role key.")
    if str(args.get("VITE_LOCAL_DEMO_MODE", "false")).lower() != "false":
        fail("FRONTEND_AUTH_BYPASS", "Frontend local demo mode must be false.")
    edge = services.get("https", {}).get("environment", {})
    domain = str(edge.get("DOMAIN") or "")
    if not https_origin("https://" + domain) or "/" in domain or placeholder(domain):
        fail("INVALID_DOMAIN", "DOMAIN must contain a real public hostname, not a URL or placeholder.")
    if edge.get("SUPABASE_URL") != supabase:
        fail("CSP_AUTH_MISMATCH", "The edge must allow the same configured Supabase origin.")
    for field in ("CORS_ORIGINS", "ALLOWED_HOSTS", "APPROVAL_ALLOWED_ROLES"):
        try:
            values = json.loads(str(backend.get(field, "[]")))
            if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                raise ValueError
        except (TypeError, ValueError):
            fail("INVALID_LIST", f"{field} requires a nonempty JSON string array.")
            continue
        if any("*" in value for value in values):
            fail("WILDCARD_ACCESS", f"{field} must not contain wildcard access.")
        if field == "CORS_ORIGINS" and ("https://" + domain not in values or any(not https_origin(v) for v in values)):
            fail("CORS_DOMAIN_MISMATCH", "CORS_ORIGINS must include the exact HTTPS deployment origin, with HTTPS origins only.")
        if field == "ALLOWED_HOSTS" and (domain.split(":")[0] not in values or "127.0.0.1" not in values):
            fail("HOST_CONFIGURATION", "ALLOWED_HOSTS must include the deployment hostname and 127.0.0.1 for healthchecks.")
        if field == "APPROVAL_ALLOWED_ROLES" and "authenticated" in [v.lower().strip() for v in values]:
            fail("OVERBROAD_APPROVAL", "The generic authenticated role must not grant approval.")
    return issues


def probe_readiness(url: str) -> dict[str, str] | None:
    if not https_origin(url):
        return {"code": "INVALID_PROBE_URL", "message": "Readiness probing requires an HTTPS origin."}
    try:
        request = Request(url.rstrip("/") + "/ready", headers={"Accept": "application/json"})
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read(65536))
            if response.status != 200 or not isinstance(data, dict) or data.get("status") != "ready":
                raise ValueError
        return None
    except (HTTPError, URLError, OSError, ValueError):
        return {"code": "NOT_READY", "message": "The live endpoint did not return HTTP 200 with JSON status=ready."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--url", help="Optional deployed HTTPS origin to probe.")
    args = parser.parse_args()
    command = ["docker", "compose", "--env-file", str(args.env_file.resolve()),
               "-f", str(ROOT / "docker-compose.yml"), "-f", str(ROOT / "docker-compose.prod.yml"),
               "--profile", "https", "--profile", "ixigo", "config", "--format", "json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=45, cwd=ROOT)
        if result.returncode:
            # Compose stderr may include substituted credentials: deliberately do not echo it.
            raise ValueError
        model = json.loads(result.stdout)
        issues = validate(model)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        issues = [{"code": "COMPOSE_UNAVAILABLE", "message": "Cannot resolve production Compose configuration. Check Docker Compose 2.24.4+, the env file, and required variables locally. Raw output is withheld to protect secrets."}]
    if args.url:
        if not issues:
            expected_domain = model.get("services", {}).get("https", {}).get("environment", {}).get("DOMAIN")
            if args.url.rstrip("/") != "https://" + str(expected_domain):
                issues.append({"code": "PROBE_DOMAIN_MISMATCH", "message": "Probe URL must match the configured deployment origin."})
        if not issues:
            issue = probe_readiness(args.url)
            if issue:
                issues.append(issue)
    print(json.dumps({"status": "blocked" if issues else "passed", "scope": "configuration_and_readiness" if args.url else "configuration_only", "issues": issues,
                      "notice": "A pass does not prove live data, authentication, device testing, or INSEF submission readiness."}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
