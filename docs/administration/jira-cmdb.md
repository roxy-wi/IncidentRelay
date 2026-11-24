---
title: Jira CMDB synchronization
description: Import services, business services and their relationships from Jira Assets / Insight.
---

# Jira CMDB synchronization

**Administration → Synchronization** supports **Services and business services · Jira CMDB** sources for Jira Data Center / Server. IR reads catalog data from Jira. A global or destination-group administrator and a running IR scheduler are required.

## Configure and import

1. Add a source and choose Jira CMDB. Enter the destination group, Jira base URL and authentication headers. Headers are encrypted and never returned; leaving the field blank on edit preserves them.
2. Set the search path: normally `/rest/assets/1.0/aql/objects`; older Insight installations may use `/rest/insight/1.0/iql/objects`. Select `qlQuery` or `iql` according to your server. Network allowlisting, TLS verification and bounded retries use the same transport as directory synchronization.
3. Enter separate AQL queries for services and business services. `objectType = "System"` and `objectType = "Product"` are editable examples. Use any object types, schemas and conditions; the queries must not select the same objects. Use a stable AQL ordering when needed for pagination.
4. Save and **Load fields and teams**. The scheduler performs discovery; the dialog shows progress. This does not change the catalog.
5. Choose the **owner team field independently for each query**. Attributes can be selected by ID or exact name. Name defaults to the object label. Description, fallback description, environment, criticality and lifecycle status are optional. After changing the owner field, save and load teams again.
6. Select an active IR team in the destination group for each CMDB team, or enable **Create missing teams in IR**. For empty selections, IR matches the full team name, ignoring case and surrounding whitespace. The preview lists new teams for creation on Apply. Choose a team manually for ambiguous names. Several CMDB teams can share the same manual selection. IR saves the resulting ID mappings and uses the same setting on scheduled runs.
7. Choose which objects contain the relationship and its reference attribute. For example, `System.Product` makes a service a component of a business service. Multiple references and the reverse direction are supported.
8. To import technical dependencies, select **Service dependency field** under **Services**, for example `Prod System`. If system A lists B in that field, IR records that A depends on B. The field is optional and independent of the `Product` mapping.
9. Save, **Preview**, review, then **Apply**. Enabling a schedule does not bypass approval. After Apply, the selected schedule starts automatically.

Under **Environment and criticality value mappings**, configure JSON dictionaries `environment_values`, `criticality_values`, and `business_criticality_values`. Unknown selected values require an explicit mapping. Lifecycle status, including Assets `status.name`, is stored in `metadata.jira_cmdb` and never overwrites operational health.

## Ownership and updates

The preview lists technical dependencies as `dependency`, with the CMDB IDs in `service` and `depends_on_service`. New dependencies use the catalog defaults (`hard`, `important`). IR preserves manual dependencies and local edits to dependency settings. It removes a source-created dependency when both services are imported and the reference disappears. Clearing the dependency field in the source settings stops managing these links and preserves them.

If A references B and only A matches the current AQL, IR looks up B by its CMDB ID among services previously imported by this source. An enabled service in the destination group can be used as the target. The preview shows its local ID in `depends_on_service_ir_id`. B keeps its existing catalog data. If the lookup fails or Jira marks B as archived, IR skips the dependency and shows a warning.

- The source and external object ID identify imported records. Renames keep the existing object and slug.
- When reading the owner field, IR skips teams marked `referencedObject.archived: true` by Jira Assets. A remaining active team can supply the owner. If all referenced teams are archived, IR handles the field as empty.
- When the Jira owner field is empty or absent, existing imports keep their owner and receive other updates. New business services can be created without an owner. The preview lists new technical services without an owner as skipped. Other objects can be applied immediately. A later sync imports the skipped service once Jira supplies a team mapped to IR.
- Only selected fields are managed. Local policies, channels, manual status, unrelated metadata and manually created component links are retained.
- New business services are private. Unmapped fields and new component impact settings use IR defaults. Subsequent synchronization preserves locally edited component impact settings.
- A service team change is blocked while the service retains team-specific rotation, policy or channel configuration. Resolve these settings before moving ownership.
- Missing or filtered-out objects are retained. A source-created component link is removed only when both endpoints were loaded and the relationship is absent. Component references outside the selected queries produce warnings.
- Queries, attribute selections and team mappings require a new preview. Interval changes restart the schedule from save time without another preview.
- The destination group and the Jira base URL cannot change after a successful import.

Every page is fetched before catalog writes. Duplicate IDs, changed totals, incomplete pagination, HTTP failures, expired leases and stale previews abort the import. Existing data stays intact. Failures are logged without credentials or raw Jira responses; scheduled retries use the configured interval.

## Remove or reconnect

Source deletion offers **Keep** or **Delete imported services and business services**. Keep preserves objects and their configuration. A new source for the same Jira base URL and destination group reconnects those objects by external ID after preview. Delete uses normal IR catalog deletion for objects created by the source, including dependent configuration. IR retains the teams, including those created automatically.

## API

Use `/api/admin/directory-sync` with `config.source_type: "jira_assets"`. `/options` includes `cmdb_preset`. `POST /{id}/inspect` queues discovery with the current `revision`. Poll `GET /{id}` for `pending_mode`, `running`, and `preview_result.attributes`, `team_catalog`, `issues`, and `warnings`. Apply requires a valid `preview_token`. Existing directory source payloads and `directory-sync:read/write` token scopes remain compatible.
