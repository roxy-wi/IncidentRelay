# Grafana OnCall OSS migration

This tool migrates supported Grafana OnCall OSS configuration to IncidentRelay
through the public HTTP APIs. It does not connect to either database.

The command is **dry-run by default**. A dry-run downloads a source snapshot,
loads current IncidentRelay resources, builds a migration plan, and writes a
report without creating or changing anything.

## Supported resources

- Users: matched by email, then username.
- Optional creation of missing users as inactive accounts.
- Grafana teams → IncidentRelay teams inside one target group.
- Group and team memberships.
- Calendar/web schedules → rotations.
- `rolling_users` and simple `recurrent_event` shifts → rotation layers.
- Future/current `single_event` shifts → rotation overrides.
- Escalation chains with `wait`, single-person notification, and schedule
  notification steps → escalation policies.
- Integrations and their default route → IncidentRelay routes.
- New IncidentRelay intake URLs and tokens are written to a protected secrets
  file during `--apply`.

## Deliberate limitations

The tool reports these items for manual conversion instead of silently changing
their meaning:

- External iCal schedules.
- Monthly recurrence.
- Cross-midnight schedule restrictions.
- Simultaneous multi-user shifts/notifications, unless `--multi-user-shift first`
  is explicitly selected.
- Arbitrary Grafana OnCall Jinja2/whole-payload regex routes.
- Outgoing webhook secrets and other masked credentials.
- Alert history.

Non-default conditional Grafana routes are created disabled because Grafana
matches against the whole payload, while IncidentRelay routes match normalized
labels. Review and configure IncidentRelay matchers before enabling them.

## Requirements

- Python 3.10 or newer.
- A Grafana OnCall API key(not grafana service accounts) with read access to users, teams, schedules,
  escalation chains, integrations, and routes(Home -> Alerts & IRM -> OnCall -> Settings).
- An IncidentRelay personal/API token belonging to a global administrator, with
  at least `resources:read` and `resources:write` scopes (or `*`).

The script uses only Python's standard library.

## Dry-run

```bash
export GRAFANA_ONCALL_TOKEN='...'
export INCIDENTRELAY_TOKEN='...'

python tools/migrations/grafana_oncall/migrate.py \
  --oncall-url https://oncall.example.com \
  --ir-url https://incidentrelay.example.com \
  --target-group production \
  --fallback-team platform \
  --users-mode existing-only
```

The target group must already exist unless `--create-target-group` is used.

Review:

```text
migration-output/
├── source/                 Raw source objects, one file per endpoint
├── snapshot.json           Combined source snapshot
├── report.json             Machine-readable plan/report
└── report.md               Human-readable plan/report
```

## Apply

After reviewing the dry-run:

```bash
python tools/migrations/grafana_oncall/migrate.py \
  --oncall-url https://oncall.example.com \
  --ir-url https://incidentrelay.example.com \
  --target-group production \
  --fallback-team platform \
  --users-mode create-inactive \
  --apply
```

Apply mode additionally creates:

```text
migration-output/
├── state.json              Source ID → IncidentRelay ID mappings
└── route-secrets.json      New intake URLs/tokens, mode 0600
```

Keep both files. `state.json` makes subsequent runs idempotent. The route secret
file is the only place where generated intake tokens are stored.

## Grafana service-account tokens

When authenticating with a Grafana service-account token, also pass the Grafana
stack URL:

```bash
python tools/migrations/grafana_oncall/migrate.py \
  --oncall-url https://oncall-api.example.com \
  --grafana-url https://grafana.example.com \
  --ir-url https://incidentrelay.example.com \
  --target-group production
```

## Useful options

```text
--snapshot-only
    Download Grafana OnCall data without connecting to IncidentRelay.

--users-mode existing-only
    Do not create users. This is the safest mode for SSO installations.

--users-mode create-inactive
    Create missing users as inactive accounts without passwords.

--multi-user-shift skip
    Default. Report simultaneous-user constructs for manual conversion.

--multi-user-shift first
    Explicitly keep only the first user where IncidentRelay supports one target.

--include-past-overrides
    Import expired single-event shifts as historical overrides.

--strict
    Stop at the first warning.

--insecure
    Disable TLS verification for both systems. Avoid in production.
```

## Recommended migration sequence

1. Run `--snapshot-only` and archive the output.
2. Run a dry-run with `existing-only` users.
3. Create or synchronize missing users through SSO.
4. Run another dry-run and review all warnings.
5. Run `--apply`.
6. Configure secrets/channels and review disabled routes.
7. Replace monitoring webhook URLs using `route-secrets.json`.
8. Verify rotations and escalation policies before disabling Grafana OnCall.
