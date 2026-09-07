"""Build shareable artifacts from the current source, preserving measured data."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

if __package__:
    from .archive_safety import check_source_credentials, ensure_regular_file, include_source
    from .verify_release import file_digest, validate_paths, verify_bundle
else:
    from archive_safety import check_source_credentials, ensure_regular_file, include_source
    from verify_release import file_digest, validate_paths, verify_bundle

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return file_digest(path)


def archive(path: Path, entries: dict[str, Path]) -> None:
    validate_paths(entries)
    for source in entries.values():
        ensure_regular_file(source)
        check_source_credentials(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as stream:
        staging = Path(stream.name)
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as target:
            for name, source in sorted(entries.items()):
                target.write(source, name)
        with zipfile.ZipFile(staging) as target:
            for name, source in entries.items():
                with target.open(name) as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if checksum != digest(source):
                    raise ValueError(f"Archive verification failed: {name}")
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def manifest(path: Path, entries: dict[str, Path]) -> None:
    path.write_text("".join(f"{digest(source)}  {name}\n" for name, source in sorted(entries.items())), encoding="utf-8")


def main() -> None:
    release = ROOT / "release"
    apk = release / "EvidenceGate-v6.0.0-debug.apk"
    if not apk.is_file():
        raise ValueError("Build/provide the audited debug APK first.")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        raise ValueError("Build frontend first.")
    web = release / "EvidenceGate-v6.0.0-web.zip"
    archive(web, {p.relative_to(dist).as_posix(): p for p in dist.rglob("*") if p.is_file()})

    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    sources: dict[str, Path] = {}
    for name in sorted(set(names)):
        path = ROOT / name
        if not include_source(name, ROOT):
            continue
        check_source_credentials(path)
        sources[name] = path
    source_zip = release / "EvidenceGate-v6.0.0-source.zip"
    archive(source_zip, sources)
    release_entries = {p.name: p for p in (apk, web, source_zip)}
    for name in ("model.joblib", "metadata.json"):
        path = ROOT / "backend/artifacts/models/delay_predictor/1.1.0-benchmark" / name
        if path.is_file():
            release_entries[path.relative_to(ROOT).as_posix()] = path
    manifest(release / "SHA256SUMS.txt", release_entries)
    subprocess.run([sys.executable, str(ROOT / "submission/build_insef_report.py")], cwd=ROOT, check=True)
    pdf = ROOT / "output/pdf/EvidenceGate_INSEF_2026_27_Final_Report.pdf"
    experiments = ROOT / "submission/experiments"
    experimental_zip = ROOT / "submission/EvidenceGate_INSEF_2026_27_Experimental_Package.zip"
    experiment_entries = {
        "experiments/" + p.relative_to(experiments).as_posix(): p
        for p in experiments.rglob("*")
        if include_source(p.relative_to(ROOT).as_posix(), ROOT)
    }
    experiment_entries.update({pdf.name: pdf, "build_insef_report.py": ROOT / "submission/build_insef_report.py"})
    archive(experimental_zip, experiment_entries)
    manifest(ROOT / "submission/EvidenceGate_INSEF_2026_27_SHA256.txt", {
        "../output/pdf/" + pdf.name: pdf,
        experimental_zip.name: experimental_zip,
        **{"experiments/" + p.name: p for p in experiments.glob("*.csv")},
    })
    entries = {p.name: p for p in (apk, web, source_zip, pdf, experimental_zip)}
    entries["START_HERE.txt"] = ROOT / "submission/shareable/START_HERE.txt"
    entries["VERIFICATION_REPORT.md"] = ROOT / "docs/VERIFICATION_REPORT.md"
    entries["verify_release.py"] = ROOT / "submission/verify_release.py"
    internal_manifest = ROOT / "submission/shareable/SHA256SUMS.txt"
    manifest(internal_manifest, entries)
    entries[internal_manifest.name] = internal_manifest
    bundle = ROOT / "output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip"
    archive(bundle, entries)
    manifest(bundle.with_suffix(".zip.sha256"), {bundle.name: bundle})
    verify_bundle(bundle, bundle.with_suffix(".zip.sha256"))
    print(f"Source files: {len(sources)}; bundle bytes: {bundle.stat().st_size}; SHA256: {digest(bundle)}")


if __name__ == "__main__":
    main()
