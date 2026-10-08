"""Audit pack for a CERT-In empanelled auditor / STQC: what they need, generated from the code and evidence.

    python -m india_rail audit-pack [--out seva2026/evidence/audit/audit_pack]

Writes:
* sbom.cdx.json - CycloneDX 1.5 software bill of materials: every package the service runs on (requirements.txt
  and everything they pull in), with version, licence and package URL;
* evidence_index.json - every evidence file, readiness document and source file with its SHA-256, and the git
  commit, so the auditor can tell that what they review is what was tested;
* controls.json - the controls an auditor checks (CERT-In Directions 2022, OWASP ASVS, DPDP Act 2023, the
  railway's own safety boundaries), each with where it is implemented, how it is tested and what is left to
  the deployment.

The pack documents; it does not replace the independent audit, which only an empanelled auditor can do.
"""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404 - reads the git commit with fixed arguments
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from india_rail.ingest import PACKAGE_ROOT

OUT = PACKAGE_ROOT / "seva2026" / "evidence" / "audit" / "audit_pack"
EVIDENCE_GLOBS = ("seva2026/evidence/**/*.json", "seva2026/railway_readiness/*.md", "seva2026/*.md", "*.md",
                  "india_rail/**/*.py", "india_rail/**/*.js", "india_rail/**/*.html", "india_rail/**/*.css",
                  "tests/*.py", "Dockerfile", "requirements.txt", "docker-compose.railguard.yml")  # fmt: skip
SKIP_IN_SBOM = {"pytest", "ruff", "httpx"}  # test and lint tools: not part of the running service


def _licence(dist: metadata.Distribution) -> str | None:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0][:80] if text else None


def sbom(requirements: Path = PACKAGE_ROOT / "requirements.txt") -> dict[str, Any]:
    """Every package the service runs on, as installed where this runs (build it inside the production image for
    the deployed bill); pinned versions that differ from the installed ones are listed, never hidden."""

    from packaging.requirements import Requirement

    pins, queue = {}, []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        req = Requirement(text)
        if req.name.lower() in SKIP_IN_SBOM:
            continue
        pins[req.name.lower().replace("_", "-")] = str(req.specifier).lstrip("=") or None
        queue.append((req.name, tuple(sorted(req.extras))))
    seen: dict[str, metadata.Distribution] = {}
    missing = []
    while queue:
        name, extras = queue.pop()
        key = name.lower().replace("_", "-")
        if key in seen and not extras:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        seen[key] = dist
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is None or any(req.marker.evaluate({"extra": e}) for e in ("", *extras)):
                queue.append((req.name, tuple(sorted(req.extras))))
    components, mismatches = [], []
    for key in sorted(seen):
        dist = seen[key]
        name, version = dist.metadata["Name"], dist.version
        if pins.get(key) and pins[key] != version:
            mismatches.append(f"{name}: pinned {pins[key]}, installed {version}")
        components.append({
            "type": "library",
            "bom-ref": f"pkg:pypi/{key}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{key}@{version}",
            **({"licenses": [{"license": {"name": lic}}]} if (lic := _licence(dist)) else {}),
        })  # fmt: skip
    properties = [{"name": "pin_differs_from_installed", "value": m} for m in mismatches]
    properties += [{"name": "not_installed_here", "value": m} for m in sorted(missing)]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "component": {"type": "application", "name": "clear-path-nexus-railguard", "bom-ref": "railguard"},
            "properties": properties,
        },
        "components": components,
    }


def _git_commit() -> str | None:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PACKAGE_ROOT, capture_output=True, text=True,
                              check=False, timeout=10)  # nosec B603 B607 - fixed arguments  # fmt: skip
        return done.stdout.strip() or None
    except OSError:
        return None


def evidence_index(root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    files = sorted({p for g in EVIDENCE_GLOBS for p in root.glob(g) if p.is_file() and "__pycache__" not in p.parts})
    index = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"git_commit": _git_commit(), "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "files": len(index), "sha256": index}  # fmt: skip


CONTROLS = [
    # (framework, control, implementation, verification, left to the deployment)
    ("CERT-In Directions 2022 (i)", "ICT clocks synchronised with NIC or NPL NTP",
     "railguard/ops.py: SNTP check (RAILGUARD_NTP), CLOCK_DRIFT alert, readiness, metric",
     "tests/test_ops.py::test_sntp_*, test_a_drifting_clock_*",
     "point RAILGUARD_NTP at samay1.nic.in / time.nplindia.org"),
    ("CERT-In Directions 2022 (iv)", "ICT logs kept 180 days within India",
     "JSON access logs (ops.JsonFormatter); hash-chained audit files (RAILGUARD_AUDIT_DIR), timestamped UTC",
     "tests/test_security.py (audit chain, MACs)", "host in India; retain logs and audit files >= 180 days"),
    ("CERT-In Directions 2022 (ii)", "Report cyber incidents within 6 hours",
     "SECURITY.md incident procedure; audit chain for forensics", "incident drill (operator)",
     "name the point of contact; run the drill"),
    ("OWASP ASVS L2 V2/V3", "Authentication and session management",
     "accounts.py: scrypt, lockout, hashed sessions, absolute and idle expiry, roles",
     "tests/test_accounts.py, tests/test_attacks_live.py", "IR identity (SSO/LDAP) if required"),
    ("OWASP ASVS L2 V4", "Access control: least privilege",
     "security.py roles (viewer, controller, feed, admin); run-scoped cab capabilities (live.py)",
     "tests/test_security.py, tests/test_attacks_live.py", None),
    ("OWASP ASVS L2 V5", "Input validation and injection",
     "StrictRequest schemas, patterns on every path parameter, parameterised SQL, body size limits",
     "tests/test_attacks.py, tests/test_attacks_live.py", None),
    ("OWASP ASVS L2 V9", "Communications: no keys or tokens in clear text",
     "TLS at the proxy (DEPLOYMENT.md); feed-conformance refuses plain HTTP off this machine; cab capability "
     "in the URL fragment", "tests/test_conformance.py::test_keys_never_travel_in_clear_text", "TLS certificates"),
    ("OWASP ASVS L2 V10/V14", "Supply chain and configuration",
     "pinned requirements, digest-pinned base image, non-root read-only container, SBOM (this pack)",
     "pip-audit 0 known vulnerabilities; Bandit 0 findings (audit_summary.json)", "rebuild on advisories"),
    ("OWASP ASVS L2 V7", "Logging without secrets",
     "access logs carry route templates, never tokens, bodies or query strings",
     "tests/test_attacks_live.py::test_cab_tokens_never_reach_logs_or_the_audit_chain", None),
    ("Integrity of live data", "Signed, fresh, non-replayed feeds",
     "livefeed.py: HMAC-SHA256 envelopes, +-120 s window, nonces, increasing sequences",
     "tests/test_livefeed.py, tests/test_conformance.py (endpoint battery)", "per-source keys exchanged out of band"),
    ("DPDP Act 2023", "Personal data minimised",
     "no passenger or PNR data; staff accounts only (name, role, hashes); feed contract refuses extra fields",
     "COMPLIANCE_REGISTER.md; tests/test_conformance.py (extra fields refused)", "retention and notice for staff"),
    ("Railway safety boundary", "Advisory only: no interface to signalling, interlocking, Kavach or brakes",
     "no such interface exists in the code; every output needs a named controller's approval",
     "SAFETY_AND_INTEGRATION_BOUNDARIES.md; simulation invariants (APPROVAL_GATE)", "IR safety acceptance"),
]  # fmt: skip


def build(out: Path = OUT) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    bom = sbom()
    (out / "sbom.cdx.json").write_text(json.dumps(bom, indent=1) + "\n", encoding="utf-8")
    index = evidence_index()
    (out / "evidence_index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    controls = [{"framework": f, "control": c, "implementation": i, "verification": v, "left_to_deployment": d}
                for f, c, i, v, d in CONTROLS]  # fmt: skip
    (out / "controls.json").write_text(json.dumps(controls, indent=1) + "\n", encoding="utf-8")
    return {
        "out": str(out),
        "sbom_components": len(bom["components"]),
        "sbom_notes": [p["value"] for p in bom["metadata"]["properties"]],
        "evidence_files_hashed": index["files"],
        "git_commit": index["git_commit"],
        "controls": len(controls),
        "controls_left_to_deployment": sum(1 for c in controls if c["left_to_deployment"]),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m india_rail audit-pack", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.out), indent=2))
    return 0
