"""Run with python -m unittest discover -s submission/tests -v."""
import hashlib
import base64
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from submission.archive_safety import check_source_credentials, include_source
from submission.package_release import archive
from submission.verify_release import file_digest, parse_manifest, validate_name, verify_bundle


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, name="README.md", content=b"research prototype"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def bundle(self, manifest=None, extras=None):
        content = b"tested source bytes"
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / "bundle.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("source.txt", content)
            bundle.writestr("SHA256SUMS.txt", manifest or f"{digest}  source.txt\n")
            for name, value in (extras or {}).items():
                bundle.writestr(name, value)
        return path

    def test_portable_paths(self):
        for name in ("../secret", "/absolute", "C:/file", "a\\b", "a//b", "a/./b",
                     "a/../b", "a:stream", "CON.txt", "x/Lpt1.log", "a.", "a ",
                     "a\nb", "", "a/", "a|b", "a?b", "a*b", "a<b", 'a"b', "a>b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_name(name)
        validate_name("backend/app/main.py")

    def test_private_files_are_excluded(self):
        for name in (".env", ".env.local", ".env.production", "backend/.ENV.local",
                     "id_ed25519", ".npmrc", "credentials.json", "private.pem",
                     "auth.pfx", "signing.key", "android/key.properties",
                     "node_modules/a.js", "output/report.pdf", ".ruff_cache/x"):
            self.source(name)
            with self.subTest(name=name):
                self.assertFalse(include_source(name, self.root))
        for name in (".env.example", "backend/.env.example", "README.md", "app.py"):
            self.source(name)
            self.assertTrue(include_source(name, self.root))

    def test_external_file_is_excluded(self):
        self.assertFalse(include_source("../" + self.root.name + "/missing", self.root))
        # A linked parent can hide an external credential under an innocuous name.
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, "settings.txt").write_text("secret", encoding="utf-8")
            link = self.root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Host does not grant symlink creation")
            self.assertFalse(include_source("linked/settings.txt", self.root))

    def test_secret_markers_rejected_without_echoing_value(self):
        for content in (b"-----BEGIN " + b"PRIVATE KEY-----",
                        b"ghp_" + b"a" * 40, b"sb_" + b"secret_" + b"a" * 30):
            path = self.source(content=content)
            with self.assertRaises(ValueError) as error:
                check_source_credentials(path)
            self.assertNotIn(content.decode(), str(error.exception))

    def test_secret_marker_crossing_chunk_boundary(self):
        path = self.source(content=b" " * (1024 * 1024 - 8) + b"-----BEGIN " + b"PRIVATE KEY-----")
        with self.assertRaises(ValueError):
            check_source_credentials(path)

    def test_archive_is_verified_and_old_copy_survives_failure(self):
        target = self.root / "release.zip"
        source = self.source()
        archive(target, {"README.md": source})
        original = target.read_bytes()
        with self.assertRaises(FileNotFoundError):
            archive(target, {"missing.txt": self.root / "missing"})
        self.assertEqual(original, target.read_bytes())
        self.assertEqual([], list(self.root.glob("*.partial")))

    def test_archive_rejects_traversal_and_case_collision(self):
        source = self.source()
        for entries in ({"../README.md": source}, {"a": source, "A": source},
                        {"A": source, "a/file.txt": source}):
            with self.assertRaises(ValueError):
                archive(self.root / "bad.zip", entries)

    def test_archive_checks_linked_payloads(self):
        source = self.source()
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(ValueError, "Linked"):
                archive(self.root / "bad.zip", {"README.md": source})

    def test_legacy_service_role_jwt_is_rejected_but_anon_allowed(self):
        def token(role):
            header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
            payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).rstrip(b"=")
            return header + b"." + payload + b"." + b"testsignature"
        with self.assertRaises(ValueError):
            check_source_credentials(self.source(content=token("service_role")))
        check_source_credentials(self.source(content=token("anon")))

    def test_complete_bundle_with_trusted_outer_checksum(self):
        path = self.bundle()
        checksum = self.source("bundle.zip.sha256", f"{file_digest(path)}  bundle.zip\n".encode())
        self.assertEqual(1, verify_bundle(path, checksum))

    def test_wrong_outer_checksum(self):
        path = self.bundle()
        checksum = self.source("bundle.zip.sha256", f"{'0' * 64}  bundle.zip\n".encode())
        with self.assertRaisesRegex(ValueError, "Outer"):
            verify_bundle(path, checksum)

    def test_payload_corruption(self):
        path = self.bundle(manifest=f"{'0' * 64}  source.txt\n")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            verify_bundle(path)

    def test_unlisted_payload_rejected(self):
        path = self.bundle(extras={"unlisted.txt": b"payload"})
        with self.assertRaisesRegex(ValueError, "every payload"):
            verify_bundle(path)

    def test_unsafe_bundle_entry_rejected(self):
        path = self.bundle(extras={"../outside": b"payload"})
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            verify_bundle(path)

    def test_symlink_entry_rejected(self):
        path = self.bundle()
        with zipfile.ZipFile(path, "a") as bundle:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, "source.txt")
        with self.assertRaisesRegex(ValueError, "symbolic"):
            verify_bundle(path)

    def test_expansion_limit(self):
        path = self.bundle()
        with patch("submission.verify_release.MAX_EXPANDED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "limits"):
                verify_bundle(path)

    def test_manifest_invalid_duplicate_or_traversal(self):
        for manifest in ("", "abc  file", f"{'0' * 64}  ../outside",
                         f"{'0' * 64}  a\n{'1' * 64}  A\n"):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                parse_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
