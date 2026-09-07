"""Build shareable artifacts from the current source, preserving measured data."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(path: Path, entries: dict[str, Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, source in sorted(entries.items()):
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            target.write(source, name)
    with zipfile.ZipFile(path) as target:
        assert target.testzip() is None
        for name, source in entries.items():
            assert hashlib.sha256(target.read(name)).hexdigest() == digest(source)


def manifest(path: Path, entries: dict[str, Path]) -> None:
    path.write_text("".join(f"{digest(source)}  {name}\n" for name, source in sorted(entries.items())), encoding="utf-8")


def main() -> None:
    release = ROOT / "release"
    apk = release / "EvidenceGate-v6.0.0-debug.apk"
    assert apk.is_file(), "Build/provide the audited debug APK first."
    dist = ROOT / "frontend/dist"
    assert (dist / "index.html").is_file(), "Build frontend first."
    web = release / "EvidenceGate-v6.0.0-web.zip"
    archive(web, {p.relative_to(dist).as_posix(): p for p in dist.rglob("*") if p.is_file()})

    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    sources: dict[str, Path] = {}
    for name in sorted(set(names)):
        parts = PurePosixPath(name).parts
        path = ROOT / name
        if not name or not path.is_file() or path.is_symlink():
            continue
        if parts[0] in {"release", "output", "tmp", ".git"}:
            continue
        if any(p in {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".gradle", ".tools"} for p in parts):
            continue
        if (path.name.startswith(".env") and not path.name.endswith(".example")) or path.name in {"local.properties", "key.properties"}:
            continue
        if path.suffix.lower() in {".zip", ".apk", ".jks", ".keystore", ".pyc"} or "SHA256" in path.name:
            continue
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
    experiment_entries = {"experiments/" + p.name: p for p in experiments.iterdir() if p.is_file()}
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
    internal_manifest = ROOT / "submission/shareable/SHA256SUMS.txt"
    manifest(internal_manifest, entries)
    entries[internal_manifest.name] = internal_manifest
    bundle = ROOT / "output/shareable/EvidenceGate_INSEF_2026_27_COMPLETE_SHAREABLE.zip"
    archive(bundle, entries)
    manifest(bundle.with_suffix(".zip.sha256"), {bundle.name: bundle})
    print(f"Source files: {len(sources)}; bundle bytes: {bundle.stat().st_size}; SHA256: {digest(bundle)}")


if __name__ == "__main__":
    main()
