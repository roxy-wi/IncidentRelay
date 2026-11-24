---
title: Incident Management
description: Operational Incident collaboration and technical AlertGroup boundaries in 2.5.
---

# Incident management

IncidentRelay separates technical signals from operational response:

```text
Alert -> AlertGroup -> optional Incident
```

An AlertGroup owns grouping, source state, ACK/resolve, escalation, technical
assignment and technical comments. An Incident owns its workflow, operational
assignee, commander/responders, stakeholders, comments, affected services,
root cause and resolution summary.

An AlertGroup can exist without an Incident. An Incident can exist without an
AlertGroup and can link several groups without merging their technical history.
Resolving a technical group does not automatically resolve or close the Incident.
A linked group reopening can move a `resolved` or `monitoring` Incident back to
`investigating`; explicit closure remains an operational decision.

## Workspace and APIs

The workspace at `/incidents/<id>` brings together the workflow, assignments,
stakeholders, comments, affected services and activity. Read access and response
permissions are checked on the server. Linked groups and service resources are
also filtered by their owning team's access rules.

- `/api/alert-groups` manages technical AlertGroups.
- `/api/incidents` manages operational Incidents. These IDs are not interchangeable.
- `/api/incidents/<id>/activity` combines operational records with readable,
  currently linked technical records. Entries retain their source and author;
  comments appear once. `limit` is 1–500, default 200, newest first, without paging.
- `/api/incidents/<id>/comments` contains only operational comments.
- `/api/incidents/<id>/affected-services` exposes service links, runbooks,
  readable dependencies and aggregate impact. Hidden dependency details stay hidden.

The Incident detail response supplies `row_version`. Send it when changing Incident
fields, status or assignee. On `409`, reload the current record and reconcile your
edit before retrying. Collaboration actions have their own conflict rules.
Workspace and collaboration timestamps use explicit UTC; the UI formats local time.

## AlertGroup link types

In **Linked AlertGroups**, a responder can choose the link type when adding a group
or change it using the selector next to an existing group. Use `primary` for the
main signal, `related` for additional context, `symptom` for an observed effect
and `duplicate` for a group that reports the same problem. Only one active link
per Incident can be primary. An AlertGroup can belong to at most one open Incident.

To edit an active link, send `PATCH /api/incidents/{incident_id}/alert-groups/{group_id}`
with the link's `id` as `link_id`, its `incident_row_version` as `row_version`, and
the new `relation_type`. A successful edit keeps the link ID and original creator
and records both types in the Incident activity and audit log. The response
contains the updated link and Incident version. On `409`, reload the Incident and
links before retrying. Closed and cancelled Incidents cannot be edited this way.

## Reading

1. [2.5 release notes and release gates](release-notes-2.5.md)
2. [2.4 → 2.5 collaboration migration](collaboration-migration-2.5.md)
3. [Responders and participants](responders.md)
4. [Stakeholders and delivery](stakeholders.md)
5. [Service default stakeholders](../services/default-stakeholders.md)
6. [Technical alert comments](../usage/alert-comments.md)
7. [2.3 API migration](api-migration-2.3.md) and [long-term roadmap](../architecture/incident-management-v2.md)
