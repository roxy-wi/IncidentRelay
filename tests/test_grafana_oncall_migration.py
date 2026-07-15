import tempfile
import unittest
from pathlib import Path

from tools.migrations.grafana_oncall.migrate import (
    Config,
    Migrator,
    Reporter,
    StateStore,
    cadence_from_shift,
    slugify,
)


class FakeIncidentRelayClient:
    def __init__(self):
        self.base_url = "https://ir.example.com"
        self.posts = []
        self.puts = []
        self.next_id = 100

    def get(self, path, query=None):
        static = {
            "/api/groups": [
                {
                    "id": 1,
                    "slug": "production",
                    "name": "Production",
                    "active": True,
                }
            ],
            "/api/teams": [],
            "/api/admin/users": [],
            "/api/rotations": [],
            "/api/escalation-policies": [],
            "/api/routes": [],
        }
        if path in static:
            return static[path]
        if path.endswith("/users") or path.endswith("/layers") or path.endswith("/members"):
            return []
        if path.endswith("/rules"):
            return []
        raise AssertionError(f"unexpected GET {path} {query}")

    def post(self, path, body):
        self.next_id += 1
        result = {"id": self.next_id, **body}
        if path == "/api/routes":
            result["intake_token"] = "secret-route-token"
        self.posts.append((path, body, result))
        return result

    def put(self, path, body):
        self.puts.append((path, body))
        return body


def source_fixture():
    return {
        "users": [
            {
                "id": "U1",
                "username": "alice",
                "email": "alice@example.com",
                "role": "admin",
                "teams": ["T1"],
                "slack": [{"user_id": "USLACK", "team_id": "TSLACK"}],
            }
        ],
        "teams": [
            {
                "id": "T1",
                "name": "Platform",
                "email": "platform@example.com",
            }
        ],
        "schedules": [
            {
                "id": "S1",
                "name": "Platform primary",
                "type": "calendar",
                "team_id": "T1",
                "time_zone": "UTC",
                "shifts": ["OH1"],
            }
        ],
        "on_call_shifts": [
            {
                "id": "OH1",
                "name": "Daily layer",
                "type": "rolling_users",
                "team_id": "T1",
                "time_zone": "UTC",
                "start": "2026-01-01T09:00:00+00:00",
                "duration": 86400,
                "frequency": "daily",
                "interval": 1,
                "rolling_users": [["U1"]],
            }
        ],
        "escalation_chains": [
            {"id": "C1", "name": "Platform escalation", "team_id": "T1"}
        ],
        "escalation_policies": [
            {
                "id": "EP1",
                "escalation_chain_id": "C1",
                "position": 0,
                "type": "wait",
                "duration": 300,
            },
            {
                "id": "EP2",
                "escalation_chain_id": "C1",
                "position": 1,
                "type": "notify_on_call_from_schedule",
                "notify_on_call_from_schedule": "S1",
            },
        ],
        "integrations": [
            {
                "id": "I1",
                "name": "Grafana alerts",
                "team_id": "T1",
                "type": "grafana",
                "link": "https://oncall.example.com/integrations/v1/grafana/secret/",
                "default_route": {
                    "id": "R1",
                    "integration_id": "I1",
                    "escalation_chain_id": "C1",
                    "position": 0,
                    "is_the_last_route": True,
                },
            }
        ],
        "routes": [
            {
                "id": "R1",
                "integration_id": "I1",
                "escalation_chain_id": "C1",
                "position": 0,
                "is_the_last_route": True,
            }
        ],
        "outgoing_webhooks": [],
    }


class GrafanaOnCallMigrationTests(unittest.TestCase):
    def test_cadence_conversion(self):
        self.assertEqual(
            cadence_from_shift({"frequency": "daily", "interval": 1}),
            {
                "rotation_type": "daily",
                "interval_value": 1,
                "interval_unit": "days",
            },
        )
        self.assertEqual(
            cadence_from_shift({"frequency": "weekly", "interval": 2}),
            {
                "rotation_type": "custom",
                "interval_value": 2,
                "interval_unit": "weeks",
            },
        )
        self.assertIsNone(
            cadence_from_shift({"frequency": "monthly", "interval": 1})
        )

    def test_slugify_is_incidentrelay_safe(self):
        self.assertEqual(slugify("Platform & SRE"), "platform-sre")
        self.assertEqual(slugify("___"), "imported-")

    def test_dry_run_plans_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ir = FakeIncidentRelayClient()
            state = StateStore(
                tmp_path / "state.json",
                "https://oncall.example.com",
                ir.base_url,
            )
            config = Config(
                apply=False,
                strict=False,
                users_mode="create-inactive",
                target_group_id=1,
                target_group=None,
                create_target_group=False,
                fallback_team=None,
                multi_user_shift="skip",
                include_past_overrides=False,
                output_dir=tmp_path,
            )
            reporter = Reporter()

            Migrator(source_fixture(), ir, state, reporter, config).run()

            self.assertEqual(ir.posts, [])
            self.assertEqual(ir.puts, [])
            self.assertTrue(any(event.level == "plan" for event in reporter.events))
            self.assertFalse((tmp_path / "route-secrets.json").exists())

    def test_apply_migrates_supported_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            ir = FakeIncidentRelayClient()
            state = StateStore(
                tmp_path / "state.json",
                "https://oncall.example.com",
                ir.base_url,
            )
            config = Config(
                apply=True,
                strict=False,
                users_mode="create-inactive",
                target_group_id=1,
                target_group=None,
                create_target_group=False,
                fallback_team=None,
                multi_user_shift="skip",
                include_past_overrides=False,
                output_dir=tmp_path,
            )
            reporter = Reporter()

            Migrator(source_fixture(), ir, state, reporter, config).run()

            posted_paths = [path for path, _body, _result in ir.posts]
            self.assertIn("/api/admin/users", posted_paths)
            self.assertIn("/api/teams", posted_paths)
            self.assertTrue(any(path.startswith("/api/rotations") for path in posted_paths))
            self.assertIn("/api/escalation-policies", posted_paths)
            self.assertIn("/api/routes", posted_paths)

            user_payload = next(
                body for path, body, _ in ir.posts if path == "/api/admin/users"
            )
            self.assertFalse(user_payload["active"])
            self.assertFalse(user_payload["is_admin"])
            self.assertEqual(user_payload["slack_user_id"], "USLACK")

            rule_payload = next(
                body for path, body, _ in ir.posts if path.endswith("/rules")
            )
            self.assertEqual(rule_payload["delay_seconds"], 300)
            self.assertEqual(rule_payload["target_type"], "rotation")

            self.assertIsNotNone(state.get("users", "U1"))
            self.assertIsNotNone(state.get("teams", "T1"))
            self.assertIsNotNone(state.get("rotations", "S1"))
            self.assertIsNotNone(state.get("routes", "I1:R1"))

            secrets = (tmp_path / "route-secrets.json").read_text(encoding="utf-8")
            self.assertIn("secret-route-token", secrets)
            self.assertIn("https://ir.example.com/api/integrations/grafana", secrets)


if __name__ == "__main__":
    unittest.main()
