"""Synthetic configuration fixtures; none are deployment credentials."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "deployment_preflight.py"
spec = importlib.util.spec_from_file_location("deployment_preflight", MODULE)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def config():
    env = {"ENVIRONMENT": "production", "SECRET_KEY": "synthetic-session-" + "a" * 32,
           "EVIDENCE_SIGNING_KEY": "synthetic-evidence-" + "b" * 32,
           "EVIDENCE_SIGNING_KEY_ID": "test-v1", "POSTGRES_PASSWORD": "synthetic-db-" + "c" * 20,
           "SUPABASE_URL": "https://auth.evidencegate.test", "AUTH_DISABLED": "false",
           "DEBUG": "false", "DEMO_DATA_ENABLED": "false",
           "CORS_ORIGINS": '["https://evidencegate.test"]',
           "ALLOWED_HOSTS": '["evidencegate.test","127.0.0.1"]',
           "APPROVAL_ALLOWED_ROLES": '["admin","approver"]'}
    return {"services": {
        "backend": {"environment": env}, "live-ingestor": {"environment": copy.deepcopy(env)},
        "postgres": {}, "redis": {}, "frontend": {"build": {"args": {
            "VITE_SUPABASE_URL": env["SUPABASE_URL"], "VITE_SUPABASE_ANON_KEY": "sb_publishable_synthetic_test_key_only",
            "VITE_LOCAL_DEMO_MODE": "false"}}}, "https": {"environment": {
                "DOMAIN": "evidencegate.test", "SUPABASE_URL": env["SUPABASE_URL"]}}}}


class DeploymentPreflightTests(unittest.TestCase):
    def codes(self, model):
        return {issue["code"] for issue in preflight.validate(model)}

    def test_valid_configuration(self):
        self.assertEqual(preflight.validate(config()), [])

    def test_inherited_ports_block_production(self):
        model = config()
        model["services"]["redis"]["ports"] = [{"published": "6379"}]
        self.assertIn("EXPOSED_INTERNAL_PORT", self.codes(model))

    def test_missing_worker_signing_key_detected(self):
        model = config()
        del model["services"]["live-ingestor"]["environment"]["EVIDENCE_SIGNING_KEY"]
        self.assertTrue({"UNSAFE_SECRET", "WORKER_CONFIG_MISMATCH"} <= self.codes(model))

    def test_placeholder_secrets_and_auth_project_mismatch(self):
        model = config()
        model["services"]["backend"]["environment"]["SECRET_KEY"] = "replace_with_a_random_32_character_secret"
        model["services"]["frontend"]["build"]["args"]["VITE_SUPABASE_URL"] = "https://other.test"
        self.assertTrue({"UNSAFE_SECRET", "AUTH_PROJECT_MISMATCH"} <= self.codes(model))

    def test_service_role_key_never_accepted(self):
        import base64
        for key in ("sb_secret_not_for_clients", "x." + base64.urlsafe_b64encode(b'{"role":"service_role"}').decode() + ".x"):
            self.assertFalse(preflight.is_public_supabase_key(key))

    def test_legacy_anon_key_allowed(self):
        import base64
        key = "x." + base64.urlsafe_b64encode(b'{"role":"anon"}').decode() + ".x"
        self.assertTrue(preflight.is_public_supabase_key(key))

    def test_unsafe_supabase_origins_rejected(self):
        for origin in ("http://auth.test", "https://user:password@auth.test", "https://auth.test;script-src *", "https://auth.test/path", "https://auth.test?x=1"):
            self.assertFalse(preflight.https_origin(origin))

    def test_shared_secret_detected(self):
        model = config()
        env = model["services"]["backend"]["environment"]
        env["EVIDENCE_SIGNING_KEY"] = env["SECRET_KEY"]
        self.assertIn("REUSED_SIGNING_SECRET", self.codes(model))

    def test_retired_keys_reject_active_id_and_weak_secrets(self):
        for retired in ('{"old":"short"}', '{"test-v1":"' + 'q' * 40 + '"}', '[]'):
            model = config()
            model["services"]["backend"]["environment"]["EVIDENCE_VERIFICATION_KEYS"] = retired
            self.assertIn("INVALID_RETIRED_KEYS", self.codes(model))

    def test_healthcheck_host_and_cors_must_match(self):
        model = config()
        env = model["services"]["backend"]["environment"]
        env["ALLOWED_HOSTS"] = '["evidencegate.test"]'
        env["CORS_ORIGINS"] = '["http://localhost:5173"]'
        self.assertTrue({"HOST_CONFIGURATION", "CORS_DOMAIN_MISMATCH"} <= self.codes(model))

    def test_auth_bypass_and_generic_approval_blocked(self):
        model = config()
        model["services"]["backend"]["environment"].update(AUTH_DISABLED="true", APPROVAL_ALLOWED_ROLES='["authenticated"]')
        self.assertTrue({"UNSAFE_FLAG", "OVERBROAD_APPROVAL"} <= self.codes(model))

    def test_errors_do_not_leak_values(self):
        model = config()
        model["services"]["backend"]["environment"]["SECRET_KEY"] = "sensitive-short"
        self.assertNotIn("sensitive-short", json.dumps(preflight.validate(model)))

    def test_spa_fallback_is_not_readiness(self):
        with patch.object(preflight, "urlopen") as request:
            response = request.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b"<!DOCTYPE html><title>EvidenceGate</title>"
            self.assertEqual(preflight.probe_readiness("https://evidencegate.test")["code"], "NOT_READY")

    def test_real_readiness_json_accepted(self):
        with patch.object(preflight, "urlopen") as request:
            response = request.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"status":"ready"}'
            self.assertIsNone(preflight.probe_readiness("https://evidencegate.test"))

    def test_readiness_redirects_are_never_followed(self):
        for target in ("https://other.test/ready", "http://evidencegate.test/ready", "/login"):
            self.assertIsNone(preflight.NoReadinessRedirect().redirect_request(None, None, 302, "Found", {}, target))
        with patch.object(preflight, "urlopen", side_effect=preflight.HTTPError("https://evidencegate.test/ready", 302, "Found", {}, None)):
            self.assertEqual(preflight.probe_readiness("https://evidencegate.test")["code"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
