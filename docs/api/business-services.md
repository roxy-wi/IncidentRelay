# Business Services API

Base path:

```text
/api/business-services
```

All endpoints require authentication. Group read/write permissions are enforced according to the current IncidentRelay RBAC rules.

## List Business Services

```http
GET /api/business-services?group_id=<group_id>
```

Returns Business Services visible to the current user.

For non-admin users, `group_id` is required or resolved from the active group depending on the view logic.

The list response includes recalculated status and `components_count`.

Response example:

```json
[
  {
    "id": 1,
    "group_id": 1,
    "group_name": "Production",
    "owner_team_id": 2,
    "owner_team_name": "Platform",
    "slug": "checkout",
    "name": "Checkout",
    "description": "Customer checkout flow",
    "status": "degraded",
    "status_source": "calculated",
    "status_message": "Affected components: Billing API. Calculated status: degraded, impact score=50",
    "status_updated_at": "2026-07-06T10:00:00Z",
    "manual_status": null,
    "manual_status_message": null,
    "manual_status_until": null,
    "manual_status_set_by_id": null,
    "manual_status_set_at": null,
    "manual_status_active": false,
    "criticality": "important",
    "tier": "tier_2",
    "public": true,
    "public_name": "Checkout",
    "public_description": "Customer checkout flow",
    "public_order": 100,
    "enabled": true,
    "components_count": 3
  }
]
```

## Create Business Service

```http
POST /api/business-services
```

Request body:

```json
{
  "group_id": 1,
  "owner_team_id": 2,
  "slug": "checkout",
  "name": "Checkout",
  "description": "Customer checkout flow",
  "criticality": "important",
  "tier": "tier_2",
  "public": true,
  "public_name": "Checkout",
  "public_description": "Customer checkout flow",
  "public_order": 100,
  "labels": {},
  "metadata": {},
  "enabled": true
}
```

Required fields:

```text
group_id
slug
name
```

## Get Business Service Details

```http
GET /api/business-services/{business_service_id}
```

Returns the full details payload:

```text
Business Service
+ components
+ status_history
```

The endpoint recalculates the Business Service before serialization, unless manual override is active.

Response includes component effective impact fields:

```json
{
  "id": 1,
  "slug": "checkout",
  "name": "Checkout",
  "status": "degraded",
  "status_source": "calculated",
  "components": [
    {
      "id": 10,
      "business_service_id": 1,
      "service_id": 25,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "service_status": "operational",
      "effective_status": "degraded",
      "effective_status_reason": "alert_group",
      "alert_impact_status": "degraded",
      "dependency_impact_status": "operational",
      "open_alert_groups": 1,
      "critical_open_alert_groups": 0,
      "upstream_issues_count": 0,
      "criticality": "required",
      "impact_weight": 100,
      "enabled": true
    }
  ],
  "status_history": []
}
```

## Update Business Service

```http
PUT /api/business-services/{business_service_id}
```

Request body uses the same fields as create.

The endpoint updates the Business Service and returns the serialized Business Service.

## Delete Business Service

```http
DELETE /api/business-services/{business_service_id}
```

Soft-deletes the Business Service and disables related active records as implemented by the repository.

## Recalculate Business Service

```http
POST /api/business-services/{business_service_id}/recalculate
```

Recalculates current status from effective component status and returns the full details payload.

Manual override has priority if active.

Response:

```text
Business Service details payload
```

## Set Manual Status Override

```http
POST /api/business-services/{business_service_id}/manual-status
```

Request body:

```json
{
  "status": "degraded",
  "message": "Customer impact is limited but visible.",
  "until": "2026-07-06T12:00:00Z"
}
```

Allowed `status` values:

```text
operational
degraded
partial_outage
major_outage
maintenance
```

`until` is optional. If omitted, the override remains active until cleared manually.

The endpoint returns the full details payload, including components and status history.

## Clear Manual Status Override

```http
DELETE /api/business-services/{business_service_id}/manual-status
```

Clears manual override, recalculates the Business Service, and returns the full details payload.

## List Components

```http
GET /api/business-services/{business_service_id}/components
```

Returns components for the Business Service.

Each component includes raw and effective status fields:

```json
[
  {
    "id": 10,
    "business_service_id": 1,
    "service_id": 25,
    "service_slug": "billing-api",
    "service_name": "Billing API",
    "team_id": 2,
    "team_slug": "platform",
    "team_name": "Platform",
    "service_status": "operational",
    "effective_status": "degraded",
    "effective_status_reason": "alert_group",
    "alert_impact_status": "degraded",
    "dependency_impact_status": "operational",
    "open_alert_groups": 1,
    "critical_open_alert_groups": 0,
    "upstream_issues_count": 0,
    "component_type": "technical_service",
    "criticality": "required",
    "impact_weight": 100,
    "position": 0,
    "status_rule": "inherit",
    "description": null,
    "enabled": true
  }
]
```

## Add Component

```http
POST /api/business-services/{business_service_id}/components
```

Request body:

```json
{
  "service_id": 25,
  "component_type": "technical_service",
  "criticality": "required",
  "impact_weight": 100,
  "position": 0,
  "status_rule": "inherit",
  "description": null,
  "enabled": true
}
```

Required fields:

```text
service_id
```

After create, the Business Service should be recalculated and the response should include the serialized component with effective impact fields.

Component impact fields include:

```text
effective_status
effective_status_reason
own_impact_score
alert_impact_score
dependency_impact_score
effective_impact_score
service_impact_score
component_multiplier
weighted_impact_score
```

`service_impact_score` comes from Service Impact v2. `weighted_impact_score` is the component score after criticality and impact weight are applied. Business Service status then uses combined weighted component scores.

## Update Component

```http
PUT /api/business-services/components/{component_id}
```

Request body uses the same fields as Add Component.

Changing component criticality, weight, enabled state or technical service can change the Business Service calculated status.

## Delete Component

```http
DELETE /api/business-services/components/{component_id}
```

Soft-deletes or disables the component according to repository behavior.

Business Service status should be recalculated after component deletion.

## Status History

Status history is included in the details payload.

History item fields:

```json
{
  "id": 1,
  "business_service_id": 1,
  "old_status": "operational",
  "new_status": "degraded",
  "status_source": "calculated",
  "message": "Affected components: Billing API. Calculated status: degraded, impact score=50",
  "impact_score": 50,
  "component_snapshot": [],
  "created_at": "2026-07-06T10:00:00Z"
}
```

## Alert integration

Business Service impact is refreshed by alert lifecycle hooks.

When an alert group affects a direct Business Service component, the relation is:

```text
component_alert
```

When an alert affects an upstream dependency of a Business Service component, the relation is:

```text
dependency_upstream_alert
```

Business impact records are deactivated when the alert no longer affects the Business Service.

## Error responses

Common error responses:

```json
{"error": "Business service not found"}
```

```json
{"error": "Access to this group is denied"}
```

```json
{"error": "Manual status expiration must be in the future"}
```

```json
{"error": "Technical service is required."}
```
