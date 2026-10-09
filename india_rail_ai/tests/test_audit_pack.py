"""Audit pack: the software bill of materials, the evidence index and the controls list."""

from __future__ import annotations

import hashlib
import json

from india_rail import audit_pack
from india_rail.ingest import PACKAGE_ROOT


def test_the_sbom_lists_what_the_service_runs_on_and_not_the_test_tools(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi==0.0.1  # pinned to something else on purpose\npytest==9.0.3\nnot-a-real-package==1.0\n")
    bom = audit_pack.sbom(req)
    names = {c["name"].lower() for c in bom["components"]}
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.5"
    assert {"fastapi", "starlette", "pydantic"} <= names  # with what fastapi pulls in
    assert "pytest" not in names  # a test tool is not part of the running service
    notes = [p["value"] for p in bom["metadata"]["properties"]]
    assert any(n.startswith("fastapi: pinned 0.0.1") for n in notes)  # a pin that differs is reported
    assert "not-a-real-package" in notes  # and so is a package that is not installed
    assert all(c["purl"].startswith("pkg:pypi/") for c in bom["components"])


def test_the_evidence_index_hashes_what_was_tested():
    index = audit_pack.evidence_index()
    rel = "requirements.txt"
    assert index["sha256"][rel] == hashlib.sha256((PACKAGE_ROOT / rel).read_bytes()).hexdigest()
    assert any(k.startswith("seva2026/evidence/") for k in index["sha256"])
    assert any(k.startswith("india_rail/railguard/") for k in index["sha256"])
    assert isinstance(index["uncommitted"], list)  # files that differ from the commit are named, as indexed
    assert all(not k.startswith("india_rail_ai/") for k in index["uncommitted"])
    assert not any(k.startswith("seva2026/evidence/audit/audit_pack/") for k in index["sha256"])  # not itself


def test_every_control_names_its_implementation_and_its_verification(tmp_path):
    summary = audit_pack.build(tmp_path)
    controls = json.loads((tmp_path / "controls.json").read_text())
    assert summary["controls"] == len(controls) >= 10
    assert all(c["implementation"] and c["verification"] for c in controls)
    assert any("NTP" in c["control"] for c in controls)  # CERT-In clock synchronisation
    assert (tmp_path / "sbom.cdx.json").exists() and (tmp_path / "evidence_index.json").exists()
