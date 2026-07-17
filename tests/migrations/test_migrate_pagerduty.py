import importlib.util
import json
import os
import tempfile
import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).with_name("migrate_pagerduty.py")
spec = importlib.util.spec_from_file_location("migrate_pagerduty", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class FakePagerDuty:
    def __init__(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self._users = [
            {"id": "U1", "name": "Alice Example", "email": "alice@example.com"},
            {"id": "U2", "name": "Bob Example", "email": "bob@example.com"},
        ]
        self._teams = [{"id": "T1", "name": "Platform", "description": "Platform team"}]
        self._members = {
            "T1": [
                {"user": self._users[0], "role": "manager"},
                {"user": self._users[1], "role": "observer"},
            ]
        }
        self._schedule = {
            "id": "S1",
            "name": "Primary",
            "description": "Primary on-call",
            "time_zone": "UTC",
            "teams": [{"id": "T1", "type": "team_reference"}],
            "schedule_layers": [
                {
                    "id": "L1",
                    "name": "Layer 1",
                    "rotation_turn_length_seconds": 86400,
                    "rotation_virtual_start": module.iso_z(now - timedelta(days=1)),
                    "users": [
                        {"user": {"id": "U1", "type": "user_reference"}},
                        {"user": {"id": "U2", "type": "user_reference"}},
                    ],
                    "restrictions": [
                        {
                            "type": "weekly_restriction",
                            "start_day_of_week": 1,
                            "start_time_of_day": "09:30:00",
                            "duration_seconds": 28800,
                        }
                    ],
                }
            ],
        }
        self._override = {
            "id": "O1",
            "start": module.iso_z(now + timedelta(days=1)),
            "end": module.iso_z(now + timedelta(days=2)),
            "user": {"id": "U2", "type": "user_reference"},
        }
        self._policy = {
            "id": "P1",
            "name": "Platform policy",
            "description": "Policy",
            "num_loops": 2,
            "teams": [{"id": "T1", "type": "team_reference"}],
            "escalation_rules": [
                {
                    "id": "R1",
                    "escalation_delay_in_minutes": 5,
                    "targets": [
                        {"id": "S1", "type": "schedule_reference"},
                        {"id": "U1", "type": "user_reference"},
                    ],
                }
            ],
        }
        self._service = {
            "id": "SV1",
            "name": "Payments",
            "description": "Payments service",
            "status": "active",
            "teams": [{"id": "T1", "type": "team_reference"}],
            "escalation_policy": {"id": "P1", "type": "escalation_policy_reference"},
            "html_url": "https://example.pagerduty.com/services/SV1",
        }
        self._maintenance = {
            "id": "M1",
            "summary": "Database work",
            "description": "Planned work",
            "start_time": module.iso_z(now + timedelta(hours=1)),
            "end_time": module.iso_z(now + timedelta(hours=3)),
            "services": [{"id": "SV1", "type": "service_reference"}],
            "teams": [],
        }

    def users(self):
        return list(self._users)

    def teams(self):
        return list(self._teams)

    def team_members(self, team_id):
        return list(self._members[team_id])

    def schedules(self):
        return [{"id": "S1", "name": "Primary"}]

    def schedule(self, schedule_id):
        return dict(self._schedule)

    def schedule_overrides(self, schedule_id, since, until):
        return [dict(self._override)]

    def escalation_policies(self):
        return [dict(self._policy)]

    def escalation_policy(self, policy_id):
        return dict(self._policy)

    def services(self):
        return [dict(self._service)]

    def maintenance_windows(self):
        return [dict(self._maintenance)]

    def v3_schedules(self):
        return [{"id": "V3-1", "name": "Shift schedule"}]


class FakeIncidentRelay:
    def __init__(self):
        self.base_url = "https://ir.example.com"
        self.next_id = 100
        self.posts = []
        self.groups = [{"id": 1, "name": "Production"}]
        self.users = [
            {
                "id": 10,
                "username": "alice",
                "display_name": "Alice",
                "email": "alice@example.com",
                "active": True,
            }
        ]
        self.group_users = [{"id": 1, "user_id": 10, "role": "viewer", "active": True}]
        self.teams = []
        self.team_users = {}
        self.rotations = {}
        self.layers = {}
        self.layer_members = {}
        self.layer_restrictions = {}
        self.overrides = {}
        self.policies = {}
        self.policy_rules = {}
        self.services = {}
        self.routes = {}
        self.maintenance = []

    def _id(self):
        value = self.next_id
        self.next_id += 1
        return value

    def list_groups(self):
        return list(self.groups)

    def list_users(self):
        return list(self.users)

    def list_teams(self):
        return list(self.teams)

    def list_team_users(self, team_id):
        return list(self.team_users.get(team_id, []))

    def list_group_users(self, group_id):
        return list(self.group_users)

    def list_rotations(self, team_id):
        return list(self.rotations.get(team_id, []))

    def list_rotation_layers(self, rotation_id):
        return list(self.layers.get(rotation_id, []))

    def list_layer_members(self, layer_id):
        return list(self.layer_members.get(layer_id, []))

    def list_layer_restrictions(self, layer_id):
        return list(self.layer_restrictions.get(layer_id, []))

    def list_rotation_overrides(self, rotation_id):
        return list(self.overrides.get(rotation_id, []))

    def list_policies(self, team_id):
        return list(self.policies.get(team_id, []))

    def list_policy_rules(self, policy_id):
        return list(self.policy_rules.get(policy_id, []))

    def list_services(self, team_id):
        return list(self.services.get(team_id, []))

    def list_routes(self, team_id):
        return list(self.routes.get(team_id, []))

    def list_maintenance(self, group_id):
        return list(self.maintenance)

    def put(self, path, body):
        if "/restrictions" in path:
            layer_id = int(path.split("/")[4])
            self.layer_restrictions[layer_id] = list(body["restrictions"])
            return list(body["restrictions"])
        raise AssertionError(path)

    def post(self, path, body):
        self.posts.append((path, json.loads(json.dumps(body))))
        if path == "/api/admin/users":
            item = {"id": self._id(), **body}
            self.users.append(item)
            if body.get("group_id"):
                self.group_users.append(
                    {"id": self._id(), "user_id": item["id"], "role": body["group_role"], "active": True}
                )
            return item
        if path.startswith("/api/groups/") and path.endswith("/users"):
            if not any(x["user_id"] == body["user_id"] for x in self.group_users):
                self.group_users.append({"id": self._id(), **body})
            return {"id": self._id(), **body}
        if path == "/api/teams":
            item = {"id": self._id(), **body}
            self.teams.append(item)
            return item
        if path.startswith("/api/teams/") and path.endswith("/users"):
            team_id = int(path.split("/")[3])
            item = {"id": self._id(), **body}
            self.team_users.setdefault(team_id, []).append(item)
            return item
        if path == "/api/rotations":
            item = {"id": self._id(), **body}
            self.rotations.setdefault(body["team_id"], []).append(item)
            return item
        if path.startswith("/api/rotations/") and path.endswith("/layers"):
            rotation_id = int(path.split("/")[3])
            item = {"id": self._id(), **body}
            self.layers.setdefault(rotation_id, []).append(item)
            return item
        if path.startswith("/api/rotations/layers/") and path.endswith("/members"):
            layer_id = int(path.split("/")[4])
            item = {"id": self._id(), **body}
            self.layer_members.setdefault(layer_id, []).append(item)
            return item
        if path.startswith("/api/rotations/") and path.endswith("/overrides"):
            rotation_id = int(path.split("/")[3])
            item = {"id": self._id(), **body}
            self.overrides.setdefault(rotation_id, []).append(item)
            return item
        if path == "/api/escalation-policies":
            item = {"id": self._id(), **body}
            self.policies.setdefault(body["team_id"], []).append(item)
            return item
        if path.startswith("/api/escalation-policies/") and path.endswith("/rules"):
            policy_id = int(path.split("/")[3])
            item = {"id": self._id(), **body}
            self.policy_rules.setdefault(policy_id, []).append(item)
            return item
        if path == "/api/services":
            item = {"id": self._id(), **body}
            self.services.setdefault(body["team_id"], []).append(item)
            return item
        if path == "/api/routes":
            item = {"id": self._id(), **body, "intake_token": f"secret-{self.next_id}"}
            self.routes.setdefault(body["team_id"], []).append({k: v for k, v in item.items() if k != "intake_token"})
            return item
        if path == "/api/maintenance-windows":
            item = {"id": self._id(), **body}
            self.maintenance.append(item)
            return item
        raise AssertionError(path)


class ConversionTests(unittest.TestCase):
    def test_choose_interval(self):
        self.assertEqual(module.choose_interval(86400), ("daily", 1, "days"))
        self.assertEqual(module.choose_interval(604800), ("weekly", 1, "weeks"))
        self.assertEqual(module.choose_interval(7200), ("custom", 2, "hours"))

    def test_weekly_restriction_and_midnight_wrap(self):
        converted, warnings = module.convert_restrictions(
            [
                {
                    "type": "weekly_restriction",
                    "start_day_of_week": 7,
                    "start_time_of_day": "22:30:00",
                    "duration_seconds": 10800,
                }
            ]
        )
        self.assertEqual(warnings, [])
        self.assertEqual(
            converted,
            [{"weekday": 6, "start_time": "22:30", "end_time": "01:30"}],
        )


    def test_handoff_keeps_source_local_clock(self):
        fields = module.rotation_fields(
            {
                "rotation_turn_length_seconds": 604800,
                "rotation_virtual_start": "2026-07-20T09:15:00+05:00",
            },
            "Asia/Almaty",
        )
        self.assertEqual(fields["handoff_time"], "09:15")
        self.assertEqual(fields["handoff_weekday"], 0)
        self.assertEqual(fields["start_at"], "2026-07-20T04:15:00Z")

    def test_full_apply_is_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            pd = FakePagerDuty()
            ir = FakeIncidentRelay()
            state = module.StateStore(output / "state.json", persist=True)
            secrets = module.SecretStore(output / "route-secrets.json", persist=True)
            reporter = module.Reporter()
            options = module.MigrationOptions(
                apply=True,
                group_id=1,
                selected_stages=set(module.MIGRATION_STAGES),
                missing_users="create-active",
                group_role="viewer",
                team_role="responder",
                name_prefix="PD — ",
                fallback_team_name="Imported",
                overrides_until_days=365,
                create_routes=True,
                strict=False,
            )
            migrator = module.Migrator(pd, ir, state, secrets, reporter, options)
            migrator.run(output)
            first_post_count = len(ir.posts)
            self.assertGreater(first_post_count, 0)
            self.assertTrue((output / "state.json").exists())
            self.assertTrue((output / "route-secrets.json").exists())
            self.assertEqual(os.stat(output / "route-secrets.json").st_mode & 0o777, 0o600)
            route_secret = json.loads((output / "route-secrets.json").read_text())
            self.assertIn("SV1", route_secret["routes"])
            self.assertEqual(route_secret["routes"]["SV1"]["endpoint"], "https://ir.example.com/api/integrations/webhook")

            second_state = module.StateStore(output / "state.json", persist=True)
            second_secrets = module.SecretStore(output / "route-secrets.json", persist=True)
            second_reporter = module.Reporter()
            second = module.Migrator(pd, ir, second_state, second_secrets, second_reporter, options)
            second.run(output)
            self.assertEqual(len(ir.posts), first_post_count)

            policy_rules = [item for rules in ir.policy_rules.values() for item in rules]
            self.assertEqual(len(policy_rules), 2)
            self.assertEqual(policy_rules[0]["delay_seconds"], 300)
            self.assertEqual(policy_rules[1]["delay_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
