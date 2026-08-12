# Notification Template Architecture

Status: Proposed  
Related issue: #65 — Support customizable notification templates

## Purpose

Introduce a unified notification rendering architecture for IncidentRelay without coupling templates to individual notifier implementations.

The first implementation should remain relatively small, but its data model and rendering boundaries must support future features such as reusable templates, event-specific templates, defaults, versioning, and policy-level overrides.

## Core principles

1. Notification templates are a separate domain entity, not an embedded part of `NotificationChannel.config`.
2. Channels select templates; they do not own the rendering implementation.
3. All outbound notifiers use one normalized notification context and one common renderer.
4. Templates customize notification content only. Provider-specific controls, callbacks, message metadata, ACK/Resolve buttons, and delivery tracking remain owned by the notifier.
5. The template language is intentionally limited and deterministic. It is not a general-purpose Jinja environment.
6. Existing built-in notification behavior remains the default when no custom template is selected.
7. The architecture must allow future template resolution rules without requiring notifier rewrites.
8. The unified template system is the only supported customization mechanism. Channel-specific legacy template formats are not part of the target architecture.

## Domain model

### NotificationTemplate

Initial model:

```text
NotificationTemplate
- id
- team_id
- name
- title_template
- body_template
- format
- enabled
- created_at
- updated_at
```

Recommended constraints:

- templates are team-scoped;
- names are unique within a team;
- disabled templates cannot be newly assigned to channels;
- templates use hard delete;
- deletion is rejected while any active channel references the template;
- the channel/template foreign key uses `RESTRICT`;
- template format is validated against a known set of values.

Initial formats:

```text
text
markdown
html
```

Templates are not transport-specific. Do not introduce separate models such as `SlackTemplate`, `TelegramTemplate`, or `EmailTemplate`.

### Enabled state

`enabled` is a configuration state, not a lifecycle/history mechanism.

Recommended behavior:

```text
enabled = true
→ template can be selected for new channel assignments

enabled = false
→ template remains stored but is hidden or unavailable for new assignments
```

For channels already referencing a template that later becomes disabled, the preferred behavior is:

```text
existing channel assignment
→ continues to use the template
```

This avoids silently changing notification output when an administrator temporarily disables a template.

If stricter behavior is later desired, it should be implemented explicitly rather than by automatically switching the channel to the built-in default.

### Deletion

Templates do not require soft delete because historical notification data must not depend on the current template record.

Deletion behavior:

```text
Template referenced by one or more active channels
→ DELETE rejected with 409 Conflict

Template not referenced
→ hard delete
```

The channel foreign key should use `RESTRICT`.

Do not use `SET NULL` for deletion because deleting a template must not silently switch existing channels to the built-in default.

Historical delivery records should contain the rendered notification content or provider delivery data required for history and troubleshooting. They must not require the template row to continue existing.

### NotificationChannel

A channel receives an optional template reference:

```text
notification_template_id = nullable
```

A `NULL` value means that IncidentRelay uses its built-in default rendering for that channel.

A template may be reused by multiple channels.

Example:

```text
Team
 ├── Template A
 ├── Template B
 └── Template C

Channel 1 -> Template A
Channel 2 -> Template A
Channel 3 -> Template C
Channel 4 -> built-in default
```

## Rendering flow

The notification pipeline should be structured as:

```text
Alert / Notification Event
        |
        v
build_notification_context()
        |
        v
resolve_notification_template()
        |
        v
render_notification()
        |
        v
RenderedNotification
        |
        v
Notifier
        |
        +--> Slack
        +--> Telegram
        +--> Mattermost
        +--> Email
        +--> Discord
        +--> Teams
        +--> other outbound transports
```

Notifier implementations should not independently reconstruct the main alert text once the common renderer is in place.

## Notification context

Templates should receive a normalized, structured context instead of a large flat namespace.

Initial namespaces:

```text
alert.*
event.*
team.*
service.*
assignee.*
labels.*
annotations.*
```

Examples:

```text
{{ alert.title }}
{{ alert.priority }}
{{ alert.severity }}
{{ alert.status }}
{{ alert.source }}
{{ alert.url }}

{{ event.type }}

{{ team.name }}
{{ team.slug }}

{{ service.name }}
{{ service.slug }}
{{ service.environment }}
{{ service.criticality }}
{{ service.tier }}

{{ assignee.username }}
{{ assignee.display_name }}

{{ labels.instance }}
{{ labels.alertname }}

{{ annotations.description }}
{{ annotations.runbook_url }}
```

The exact supported fields should be defined centrally and documented.

The context builder is responsible for normalizing missing data and exposing only explicitly supported values.

Raw Python objects must never be passed directly to the template renderer.

## Template syntax

Use one template syntax everywhere:

```text
{{ alert.title }}
{{ labels.instance }}
```

The first implementation should support variable substitution only.

Do not initially support:

- arbitrary Python;
- Jinja execution;
- function calls;
- loops;
- conditions;
- expressions;
- dynamic attribute traversal outside the approved context;
- filesystem or environment access.

Unknown placeholders should produce a deterministic validation or rendering result rather than executing arbitrary behavior.

Template validation should happen when a template is saved, not only during notification delivery.

## One unified template system

All customizable notifications must use the new unified template system.

Do not retain separate channel-specific template syntaxes or rendering paths.

In particular:

- Email must use the same `NotificationTemplate` entity;
- Email must use the same `{{ ... }}` placeholder syntax;
- Slack, Telegram, Mattermost, Discord, Teams, Email, and future notifiers must consume the same rendered-notification abstraction;
- notifier-specific templates stored directly in channel config are not part of the target design.

If an installation currently has an older channel-specific Email template configuration, the implementation may use a one-time database migration or explicit upgrade conversion to move it into the new model.

After the migration completes, runtime delivery should use only the new unified template system.

There should be no long-term runtime fallback to an old Email template format.

## Title and body

Templates should contain separate title and body fields:

```text
title_template
body_template
```

This avoids transport-specific redesign later.

Examples of uses:

- Email: subject + body;
- browser/mobile notification: title + body;
- Slack/Teams: headline + body;
- Telegram/Mattermost: body, optionally incorporating the title.

A notifier that does not have a distinct title concept may combine the rendered title and body.

## Rendered notification abstraction

The common renderer should return a transport-neutral object, for example:

```text
RenderedNotification
- title
- body
- format
```

The notifier then adapts this result to the provider API.

Provider-specific formatting, payload shape, button blocks, callback identifiers, and message tracking are not part of `NotificationTemplate`.

## System controls

Templates customize content but must not control IncidentRelay operational behavior.

The following remain outside user templates:

- Acknowledge controls;
- Resolve controls;
- escalation controls;
- callback payloads;
- Slack block/action identifiers;
- Telegram callback data;
- Mattermost action metadata;
- message IDs;
- delivery/update metadata;
- internal alert IDs required for provider actions.

Conceptually:

```text
Rendered custom content
        +
IncidentRelay system controls
        |
        v
Provider payload
```

This prevents a custom template from accidentally breaking ACK/Resolve or message update behavior.

## Template resolution

Template lookup must live behind a dedicated resolver:

```python
resolve_notification_template(
    channel,
    event_type,
    ...
)
```

Initial resolution:

```text
channel.notification_template_id
        |
        +-- set --> selected NotificationTemplate
        |
        +-- null -> built-in default
```

Notifier code must call the resolver rather than access `channel.notification_template_id` directly.

A disabled template that is already assigned remains resolvable for that channel.

The resolver may later support:

```text
policy/event override
        |
channel template
        |
team default
        |
system default
```

without changing notifier implementations.

## Event types

The first version does not need different templates per event type.

The notification context should nevertheless expose the event type, for example:

```text
triggered
acknowledged
resolved
escalated
reminder
```

This preserves a future path to event-specific template assignment.

Event-specific resolution is intentionally deferred.

## URLs

The common renderer should not scan arbitrary rendered text and automatically convert URLs into links.

Templates should express links according to their format.

Markdown example:

```text
[Runbook]({{ annotations.runbook_url }})
```

HTML example:

```html
<a href="{{ annotations.runbook_url }}">Runbook</a>
```

Plain-text templates simply render the URL value.

The renderer must apply appropriate escaping for the selected format and provider adaptation layer.

## Format and transport compatibility

Templates describe content format, not transport.

Initial compatibility can be treated as capabilities:

```text
text      -> all text-capable transports
markdown  -> Slack, Telegram, Mattermost, Discord, Teams where supported
html      -> Email
```

Exact provider adaptation belongs to notifier implementations.

A channel must reject a template format that its notifier cannot safely consume.

## Preview

Template preview should use the same backend context builder and renderer used for real notifications.

Do not implement an independent JavaScript renderer.

Flow:

```text
template
   +
sample notification context
   |
   v
render_notification()
   |
   v
preview
```

This prevents preview behavior from diverging from actual notifications.

The initial preview may use a stable sample context. A later version may allow previewing against a real alert.

## Initial UI

A full visual template builder is not required.

Initial Template management UI:

```text
Notification Templates

Name
Enabled
Format
Title template
Body template

[Preview]
[Save]
[Delete]
```

Delete must be unavailable or return a clear conflict when the template is referenced by active channels.

Channel configuration:

```text
Notification template
[Default                     v]
```

Disabled templates should not appear as selectable options for new assignments.

A channel already assigned to a disabled template should still display that assignment clearly.

The channel UI may also provide a shortcut to create a template, but creation still produces a real `NotificationTemplate` entity.

## Initial implementation scope

The first implementation should include:

- `NotificationTemplate` model;
- team-scoped CRUD;
- `enabled` state;
- hard delete with active-reference protection;
- `RESTRICT` foreign key from channels to templates;
- optional template assignment to Notification Channels;
- normalized notification context;
- safe placeholder validation and rendering;
- one unified `{{ ... }}` syntax;
- `text`, `markdown`, and `html` formats;
- title/body rendering;
- common template resolver;
- common rendered-notification abstraction;
- built-in default fallback;
- template preview using the backend renderer;
- one-time migration/conversion of any existing channel-specific Email template data if required;
- no runtime legacy Email template fallback;
- notifier adaptation without exposing system controls to templates;
- tests for renderer safety, resolution, enable/disable behavior, deletion protection, format compatibility, and default fallback;
- API/OpenAPI documentation.

## Explicitly deferred

Do not include in the first implementation unless another requirement makes it necessary:

- global template library;
- visual drag-and-drop template builder;
- template inheritance;
- template versioning/history;
- conditional expressions;
- loops;
- functions;
- arbitrary Jinja support;
- policy-level template overrides;
- separate template per notification event type;
- global or group-level defaults;
- template import/export;
- automatic URL detection;
- transport-specific template models.

These features should be added through the existing resolver/context/rendering boundaries rather than by changing notifier APIs.

## Architectural invariants

The following should remain true as the feature evolves:

1. Notifiers do not own template storage.
2. Templates do not own provider-specific controls.
3. User templates cannot execute arbitrary code.
4. Rendering operates only on a normalized allowlisted context.
5. Built-in default notifications continue to work without any template configuration.
6. A reusable template may be assigned to multiple channels.
7. Template resolution is centralized.
8. Preview and real delivery use the same renderer.
9. Provider-specific adaptation happens after common rendering.
10. Future policy-, event-, team-, or system-level template selection can be added without rewriting notifiers.
11. Template deletion is hard delete and is blocked while active references exist.
12. Disabled templates remain valid for existing assignments but cannot be newly assigned.
13. All customizable notifications use the unified template model and syntax.
14. Runtime delivery contains no legacy Email template rendering path.

## Future resolution model

A possible later evolution is:

```text
Notification Event
        |
        v
Template Resolver
        |
        +--> event/policy override
        |
        +--> channel template
        |
        +--> team default
        |
        +--> system default
        |
        v
Notification Context
        |
        v
Renderer
        |
        v
RenderedNotification
        |
        +--> Slack adapter + IncidentRelay controls
        +--> Telegram adapter + IncidentRelay controls
        +--> Mattermost adapter + IncidentRelay controls
        +--> Email adapter
        +--> other adapters
```

The first implementation does not need to expose all of these resolution levels. The important requirement is that its boundaries do not prevent them later.

## Decision summary

IncidentRelay should implement customizable notifications as a reusable rendering subsystem, not as ad-hoc template strings embedded independently in each notifier.

A standalone `NotificationTemplate` entity, a normalized allowlisted context, a restricted placeholder renderer, a centralized resolver, and a transport-neutral rendered result provide the desired balance.

The initial lifecycle is intentionally simple:

```text
create
update
enable / disable
delete when unused
```

Deletion is hard delete with `RESTRICT` protection. Soft delete and restore are not required.

All channels, including Email, use the new unified template system and the same placeholder syntax. Any older Email-specific template data should be converted during upgrade rather than supported as a permanent runtime compatibility path.
