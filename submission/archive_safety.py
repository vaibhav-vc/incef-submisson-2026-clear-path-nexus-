"""Source archive selection and credential safeguards; never log secret values."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath

EXCLUDED_DIRS = {"release", "output", "tmp", ".git", "node_modules", ".venv", "venv",
                 "__pycache__", "dist", "build", ".gradle", ".tools", ".ssh", ".aws",
                 ".pytest_cache", ".ruff_cache"}
PRIVATE_NAMES = {"local.properties", "key.properties", "credentials", "credentials.json",
                 "service-account.json", "id_rsa", "id_ed25519", "id_ecdsa", ".npmrc",
                 ".pypirc", ".netrc"}
PRIVATE_SUFFIXES = {".zip", ".apk", ".jks", ".keystore", ".pyc", ".pem", ".key",
                    ".p12", ".pfx", ".crt"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(rb"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
)
JWT_PATTERN = re.compile(rb"\beyJ[A-Za-z0-9_-]{1,1024}\.([A-Za-z0-9_-]{1,4096})\.[A-Za-z0-9_-]+")


def ensure_regular_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.absolute() != path.resolve():
        raise ValueError(f"Linked files cannot be packaged: {path.name}")
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, "is_junction") and component.is_junction()):
            raise ValueError(f"Linked files cannot be packaged: {path.name}")


def contains_privileged_jwt(data: bytes) -> bool:
    for match in JWT_PATTERN.finditer(data):
        payload = match.group(1)
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4)))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(claims, dict) and claims.get("role") == "service_role":
            return True
    return False


def include_source(name: str, root: Path) -> bool:
    parts = PurePosixPath(name).parts
    path = root / name
    if not name or not parts or not path.is_file():
        return False
    if any(p.lower() in EXCLUDED_DIRS for p in parts):
        return False
    # is_file follows links: reject symlinked parents, junctions and paths outside
    # the repository, not only a symlink at the final component.
    if not path.resolve().is_relative_to(root.resolve()):
        return False
    if path.absolute() != path.resolve():
        return False
    current = root
    for part in parts:
        current /= part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            return False
    basename = path.name.lower()
    if ((basename.startswith(".env") and not basename.endswith(".example"))
            or basename in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES
            or "sha256" in basename):
        return False
    return True


def check_source_credentials(path: Path) -> None:
    """Conservative signatures complement filename exclusions, not a full audit."""
    with path.open("rb") as stream:
        tail = b""
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            if any(pattern.search(data) for pattern in SECRET_PATTERNS) or contains_privileged_jwt(data):
                raise ValueError(f"Possible private credential in source file: {path.name}")
            tail = data[-8192:]
