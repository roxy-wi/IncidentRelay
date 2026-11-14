---
title: GitLab deployments
description: Native Deployment webhooks for Change Intelligence
---

# GitLab deployments → Change Intelligence

GitLab sends its standard **Deployment events**. IncidentRelay creates a Change,
associates configured Services and projects its lifecycle. No notification script
or custom JSON template is required in your pipeline.

## Configure IncidentRelay

1. A global administrator enables **Accept Change Events** and **Background change
   processing** in **Administration → System settings**.
2. Create a **Change integration**, selecting its Group and owner Team. Its first
   source is created automatically.
3. On **Permissions**, give the source **Changed** permission for the target
   Services or their entire Team.
4. On **Sources**, choose **Edit source**. In **GitLab deployments**, add a mapping
   with the GitLab project ID, exact environment name and one or more IR Services.
   Save the source.
5. On **Tokens**, issue an integration credential. Save the secret when displayed;
   it is not revealed again.

Use a separate source for each GitLab instance because external IDs can overlap.
The source defines the Change's owner Team. Use another source for another owner.
Group-owned integrations remain restricted to their Group; global administrators
can also manage central integrations.

## Mapping Teams and Services

GitLab does not need IR resource IDs. IR matches `project.id` and `environment`
against its source configuration:

| GitLab project | Environment | Source owner Team | Changed IR Services |
|---|---|---|---|
| 42 | production | Platform | API, Worker |
| 42 | staging | Platform | Staging API |
| 73 | production | Platform | Database |

Matches are exact and case-sensitive, without wildcards. Each project/environment
pair has one rule; select multiple Services in that rule. Unmatched events return
`200` with `status: ignored` and `reason: no_matching_mapping`, creating no Change.
Removing all rules disables new native events for that URL.

The Service picker lists active `changed` grants. Mapping configuration does not
grant authority: every new event checks current token, integration, source, Team,
Service and grant state. Revoked permissions can invalidate an existing mapping;
update it or restore the intended permission. Disable the source or revoke its
token to deny all access, including redeliveries.

## Configure GitLab

In the project, open **Settings → Webhooks → Add new webhook**:

| Field | Value |
|---|---|
| URL | Copy **Webhook URL** from the IR source editor |
| Secret token | The IR integration credential |
| Trigger | **Deployment events** |
| SSL verification | Enabled, with a certificate trusted by GitLab |
| Custom webhook template | Leave empty; IR expects the native payload |

Example URL: `https://ir.example.com/api/change-events/gitlab/12`. The number is
the IR **source ID**, not the integration, Team or GitLab project ID. Verify that
the externally reachable reverse-proxy address is used.

Authentication uses `X-Gitlab-Token`. `Authorization: Bearer` is also accepted;
if both headers are supplied, they must contain the same credential. A GitLab
signing token does not replace this Secret token: this endpoint does not verify HMAC.

The job must create a GitLab deployment, normally by declaring `environment`.
A successful pipeline or push alone is not a deployment. Where your GitLab edition
supports group webhooks, a source can map several projects from the same instance.

GitLab's servers must reach IR; Runner connectivity alone is insufficient. For
private networks, check GitLab's outbound webhook network restrictions.

## Verify delivery

Run a deployment or use **Test → Deployment events**. Test deliveries are processed
as real events and need a matching project/environment rule. Check **Recent events**:

| HTTP | Meaning |
|---|---|
| 201 | New event accepted |
| 200 | Existing event redelivered, or no mapping matched; inspect the response body |
| 401 | Missing, invalid or revoked integration credential; JWT/personal tokens are not accepted |
| 403 | Source or Service access denied; check activity and grants |
| 404 | Intake disabled or incorrect URL |
| 409 | Different content reused an event identity, or operation identity conflicts |
| 413 / 422 | Oversized request / invalid fields, event type or timestamp |
| 429 / 503 | Quota or transient contention; respect `Retry-After` when resending |

Open **Operations → Changes** to inspect the Team, Services, environment, status
and job link, when supplied. Service-level automatic correlation is a separate
setting that controls suggestions for that Service's alerts.

## Lifecycle and retries

`running`, `success`, `failed`, `canceled` become `change.started`,
`change.succeeded`, `change.failed`, `change.cancelled`. `blocked`, `approved`
and `rejected` produce `change.updated`; an approval decision does not replace
the deployment's terminal outcome. Unknown statuses return `422`.

Change identity uses the source, project ID and `deployment_id`. Event identity
also includes status and `status_changed_at`. Sender timestamps require a timezone;
receiver time is never substituted. Out-of-order events are supported. Redelivering
the same normalized event creates no duplicate, increments no revision and never
remaps the accepted event after configuration edits. Token rotation preserves identity.

GitLab routing requires `timestamp` ordering. The generic `POST /api/change-events`
contract remains unchanged. To configure mappings through the source PATCH API:

```json
{
  "expected_revision": 7,
  "gitlab_mappings": [
    {"project_id": 42, "environment": "production", "service_ids": [10, 11]}
  ]
}
```

Use the integration's current `auth_revision`. Omitting `gitlab_mappings` preserves
existing rules; `[]` clears them. Limits: 100 rules and 100 Services per rule.
Other limits are shared with [Change intake](../getting-started/configuration.md).

References: [GitLab Deployment events](https://docs.gitlab.com/user/project/integrations/webhook_events/#deployment-events)
and [webhook configuration](https://docs.gitlab.com/user/project/integrations/webhooks/).
