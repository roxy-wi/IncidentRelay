# System settings and Group inheritance

This is the design for settings that administrators can change while IR is running. The database stores two switches and twelve numeric Change Intelligence settings. All apply to the entire installation. The [configuration guide](../getting-started/configuration.md#advanced-change-intelligence-settings) lists their ranges and when edits take effect. The first setting eligible for a Group override will be chosen separately.

## Resolving a setting

Every setting starts as system-wide. When adding a Group override, the developer specifies which setting permits it, who can change it and when consumers apply the new value.

| Setting state | Value IR uses |
|---|---|
| System-wide setting | Every Group uses the system value. The API rejects an override. |
| Overrides allowed, Group inherits | The current system value. Changing it also changes the effective value for this Group. |
| Group has set a value | The Group value, even if it equals the system value. Later system changes leave this explicit choice in effect. |
| Group selects “Inherit” | Clear the override. The next read uses the current system value. |

For example, an explicit boolean `false` remains the Group's choice even if the system value later changes to `true`. A background job derives the Group from the resource it processes. The Group selected in the UI only determines which Group the administrator is viewing. An installation-wide operation reads the system value.

## Storage and writes

The `system_settings` table has one row with typed columns. Global administrators edit it under **Administration → System settings**. The planned overrides table will reference `Group` through a foreign key and allow at most one row per Group. It contains columns only for settings that allow Group overrides. A missing row or a `NULL` column means inheritance. This preserves `false` and `0` as explicit values when the setting permits them. A new Group inherits immediately, without copying system values.

A shared service returns the effective value and its source, either system or Group. For each eligible setting the Group UI offers an explicit value and a way to resume inheritance. Global administrators manage system values. Permission to edit a Group setting is explicitly delegated and checked on the server against the specific active Group and the [IR roles](../concepts/groups-and-rbac.md).

A write updates only the supplied fields. The same transaction records the actor, scope, Group ID for a Group edit, and previous and new states in the audit log. Switching from inheritance to an explicit value is an auditable change even when the effective value stays the same. Retrying an identical operation produces one audit entry in total.

## Introducing the first Group setting

Add the overrides table with its first consumer. Specify how that consumer identifies the Group and when it reads the setting. When moving a setting from a file, preserve its previous effective value at system scope and start all Groups in inheritance mode.

Tests on SQLite and PostgreSQL should cover two Groups with different settings, a system value change, a reset to inheritance, an explicit value equal to the system value, and denial of edits to a different Group or to a system-wide setting through the Group API. Also cover concurrent edits to different fields and rollback on audit failure.
