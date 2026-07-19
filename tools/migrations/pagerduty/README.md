# PagerDuty → IncidentRelay migration tool

`migrate_pagerduty.py` transfers PagerDuty configuration to IncidentRelay through the public HTTP APIs of both products. It does not access either database directly.

The command is **dry-run by default**. Add `--apply` only after reviewing the generated report.

## Migrated resources

- users, matched by email;
- IncidentRelay group membership;
- PagerDuty teams and team membership;
- legacy PagerDuty schedules;
- schedule layers and participant order;
- daily and weekly time restrictions;
- future schedule overrides;
- escalation policies and targets;
- services;
- IncidentRelay Webhook routes compatible with PagerDuty Events API v2;
- active and future maintenance windows.

## Deliberate limitations

- Incident and alert history is not imported.
- Event Orchestrations and Rulesets are not converted.
- PagerDuty V3 shift-based schedules are saved to the source snapshot but not imported.
- User phone numbers, contact methods, notification rules and notification channels are not copied.
- PagerDuty services with several teams are assigned to the first mapped IncidentRelay team and reported as degraded.
- A PagerDuty schedule or escalation policy shared by several teams is cloned because IncidentRelay rotations and policies belong to one team.
- Parallel targets in one PagerDuty escalation rule are converted to consecutive IncidentRelay rules. The first target keeps the original delay; additional targets use zero delay. This approximation is recorded in the report.
- Created routes have no notification channels. Configure channels or notification policies in IncidentRelay before production cutover.

## Requirements

- Python 3.10 or newer;
- a PagerDuty REST API token with read access to the resources being migrated;
- an IncidentRelay personal API token associated with a global administrator;
- an existing IncidentRelay group ID that will own the imported teams.

No third-party Python modules are required.

## Credentials

Environment variables are preferable to command-line secrets:

```bash
export PAGERDUTY_TOKEN='pd-rest-api-token'
export INCIDENTRELAY_URL='https://incidentrelay.example.com'
export INCIDENTRELAY_TOKEN='ir-admin-api-token'
```

For a PagerDuty EU account:

```bash
export PAGERDUTY_URL='https://api.eu.pagerduty.com'
```

`PAGERDUTY_FROM` can be set when your PagerDuty account requires the `From` header.

## 1. Dry-run

```bash
python migrate_pagerduty.py \
  --group-id 1 \
  --output-dir ./pagerduty-migration-output
```

A dry-run reads both APIs but performs no writes in IncidentRelay.

Review:

```text
pagerduty-migration-output/
├── plan.json
├── report.json
├── report.md
└── source/
    ├── users.json
    ├── teams.json
    ├── team_members.json
    ├── schedules.json
    ├── schedule_details.json
    ├── schedule_overrides.json
    ├── escalation_policies.json
    ├── services.json
    ├── maintenance_windows.json
    └── v3_schedules.json
```

Warnings should be reviewed before using `--apply`.

## 2. Apply

```bash
python migrate_pagerduty.py \
  --group-id 1 \
  --output-dir ./pagerduty-migration-output \
  --apply
```

The apply run additionally creates:

```text
state.json             resumable PagerDuty ID → IncidentRelay ID mappings
route-secrets.json     generated Webhook intake tokens
route-switch-map.csv   endpoint and routing_key cutover table
```

`state.json`, `route-secrets.json` and `route-switch-map.csv` are written with permissions `0600` where supported.

Do not delete `state.json` between retries. The tool saves progress after every created resource and safely resumes a partially completed migration.

## 3. Switch alert senders

For each migrated PagerDuty service, the CSV contains:

```text
endpoint=https://incidentrelay.example.com/api/integrations/webhook
routing_key=<generated IncidentRelay route intake token>
```

A PagerDuty Events API v2-compatible event can then be sent to IncidentRelay:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "<routing_key from route-switch-map.csv>",
    "event_action": "trigger",
    "dedup_key": "database-prod-01",
    "payload": {
      "summary": "Production database is unavailable",
      "source": "db-prod-01",
      "severity": "critical"
    }
  }'
```

Test `trigger` and `resolve` before changing production exporters.

## Useful options

Migrate selected stages:

```bash
python migrate_pagerduty.py --group-id 1 --only users,teams,schedules
```

Dependencies are migrated automatically. For example, the `services` stage also prepares required users, teams, schedules and escalation policies.

Skip users that do not already exist in IncidentRelay:

```bash
python migrate_pagerduty.py --group-id 1 --missing-users skip
```

Create missing users inactive:

```bash
python migrate_pagerduty.py --group-id 1 --missing-users create-inactive
```

Do not create Webhook routes:

```bash
python migrate_pagerduty.py --group-id 1 --skip-routes
```

Import overrides only for the next 90 days:

```bash
python migrate_pagerduty.py --group-id 1 --overrides-until-days 90
```

Treat any lossy conversion warning as an error:

```bash
python migrate_pagerduty.py --group-id 1 --strict
```

## Recommended cutover sequence

1. Run dry-run and resolve all unexpected warnings.
2. Back up IncidentRelay.
3. Run `--apply` in a non-production IncidentRelay environment first.
4. Compare teams, rotations and escalation policies with PagerDuty.
5. Configure IncidentRelay notification channels and notification policies.
6. Send test `trigger`, `acknowledge` and `resolve` Events API v2 payloads.
7. Switch one low-risk service using `route-switch-map.csv`.
8. Observe one on-call cycle before switching the remaining services.
9. Keep PagerDuty configuration unchanged until the IncidentRelay cutover is verified.

## Validation

```bash
python -m py_compile migrate_pagerduty.py
python -m unittest -v test_migrate_pagerduty.py
python migrate_pagerduty.py --help
```
