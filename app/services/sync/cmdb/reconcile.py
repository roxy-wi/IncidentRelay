"""Reconcile explicitly mapped catalog ownership and source-owned components."""

import re

from app.modules.common import utc_now
from app.modules.db import business_services_repo
from app.modules.db.models import (
    BusinessService, BusinessServiceComponent, DirectorySyncBinding as Binding,
    DirectorySyncSource as Source, Service, ServiceChannel, Team,
)
from app.modules.db.transactions import lock_row
from app.services.service_catalog import mutations as service_mutations
from app.services.sync.cmdb.config import CmdbConfig, is_cmdb
from app.services.sync.directory.config import SyncError


MODELS = {"service": Service, "business_service": BusinessService}


def slug_for(source_id, row):
    """Stable collision-resistant slug, assigned only on creation."""
    suffix = f"-jira-{source_id}-{row['id']}"
    name = re.sub(r"[^a-z0-9]+", "-", row["name"].lower()).strip("-") or "service"
    return name[:64 - len(suffix)].rstrip("-") + suffix


def existing_binding(source, kind, external_id):
    """Reconnect retained data only using proven external identity, never a name."""
    own = Binding.get_or_none(Binding.source == source.id, Binding.kind == kind, Binding.external_id == external_id)
    if own:
        return own
    candidates = []
    for binding in Binding.select().where(Binding.kind == kind, Binding.external_id == external_id):
        parent = binding.source
        if parent.group_id != source.group_id or not is_cmdb(parent.config) or parent.config["base_url"] != source.config["base_url"]:
            continue
        if not parent.deleted:
            raise SyncError(f"CMDB {kind} object {external_id} is already managed by source {parent.id}")
        model = MODELS.get(kind, BusinessServiceComponent)
        if model.select().where(model.id == binding.local_id, model.deleted == False).exists():
            candidates.append(binding)
    if len(candidates) > 1:
        raise SyncError(f"CMDB {kind} object {external_id} has multiple retained bindings; resolve the ownership conflict")
    return candidates[0] if candidates else None


def validate_local(source, kind, binding):
    """Recheck destination ownership under the catalog lock."""
    model = MODELS[kind]
    local = lock_row(model.select().where(model.id == binding.local_id))
    if not local or local.deleted or local.group_id != source.group_id:
        raise SyncError(f"Imported {kind} {binding.local_id} was removed or moved outside the destination group")
    if kind == "service":
        team = Team.get_by_id(local.team_id)
        if team.deleted or team.group_id != source.group_id:
            raise SyncError(f"Imported service {local.id} no longer belongs to the destination group")
    return local


def changes_for(source, row, local, team_id, kind):
    """Update managed fields while preserving other operational configuration."""
    metadata = dict(local.metadata or {}) if local else {}
    metadata["jira_cmdb"] = {"source_id": source.id, "object_id": row["id"],
                             "object_key": row["key"], "status": row["cmdb_status"]}
    values = {"name": row["name"], **row["fields"], "metadata": metadata,
              "team" if kind == "service" else "owner_team": team_id}
    if not local:
        return {**values, "group": source.group_id, "slug": slug_for(source.id, row), "public": False}
    if kind == "service" and local.team_id != team_id:
        # These settings belong to a particular Team. Moving ownership must not
        # carry another team's notification or scheduling configuration with it.
        if (local.default_rotation_id or local.default_escalation_policy_id or local.priority_policy_id
                or local.notification_policy_id or ServiceChannel.select().where(ServiceChannel.service == local.id).exists()):
            raise SyncError(f"Service {local.id}: clear or move team-specific policies, rotation and channels before changing its team")
        conflict = Service.select().where(Service.team == team_id, Service.slug == local.slug, Service.id != local.id).exists()
        if conflict:
            raise SyncError(f"Service {local.id}: its slug already exists in the destination team")
    return {key: value for key, value in values.items()
            if getattr(local, key + "_id" if key in {"team", "owner_team"} else key) != value}


def reconcile(source, snapshot):
    """Run inside the shared fenced transaction (rolled back when previewing)."""
    from app.services.change_intelligence.administration import lock_catalog

    lock_catalog()
    config = CmdbConfig.model_validate(source.config)
    changes, issues = [], list(snapshot["issues"])
    teams = {}
    for external in snapshot["team_catalog"]:
        local_id = config.team_matches.get(external["id"])
        team = lock_row(Team.select().where(Team.id == local_id)) if local_id else None
        if not team or team.deleted or not team.active or team.group_id != source.group_id:
            issues.append(f"CMDB team {external['id']}: select an active existing IR team in the destination group")
        else:
            teams[external["id"]] = team.id
    if issues:
        return {"changes": [], "issues": issues}

    locals_by_kind = {"service": {}, "business_service": {}}
    for kind, collection in (("business_service", "business_services"), ("service", "services")):
        create_object = (
            service_mutations.create_service if kind == "service"
            else business_services_repo.create_business_service
        )
        update_object = (
            service_mutations.update_service if kind == "service"
            else business_services_repo.update_business_service
        )
        for row in sorted(snapshot[collection], key=lambda item: int(item["id"])):
            binding = existing_binding(source, kind, row["id"])
            local = validate_local(source, kind, binding) if binding else None
            values = changes_for(source, row, local, teams[row["team_id"]], kind)
            reconnect = binding and binding.source_id != source.id
            if values or reconnect:
                changes.append({"kind": kind, "external_id": row["id"], "label": row["name"],
                                "action": "reconnect" if reconnect else "update" if local else "create", "fields": values})
            if not local:
                local = create_object(values)
                binding = Binding.create(source=source.id, kind=kind, external_id=row["id"], local_id=local.id, created=True)
            elif values:
                local = update_object(local.id, values)
            if reconnect:
                binding.source = source.id
                binding.owned = True
                binding.save()
            locals_by_kind[kind][row["id"]] = local

    expected_edges = set()
    warnings = []
    for row in snapshot[config.relationship_side]:
        for ref in sorted(set(row["references"])):
            service_id, business_id = (row["id"], ref) if config.relationship_side == "services" else (ref, row["id"])
            service = locals_by_kind["service"].get(service_id)
            business = locals_by_kind["business_service"].get(business_id)
            if not service or not business:
                warnings.append(f"Relationship {service_id} -> {business_id}: referenced object is outside the selected queries; existing links retained")
                continue
            external_id = f"{service_id}:{business_id}"
            expected_edges.add(external_id)
            binding = existing_binding(source, "component", external_id)
            component = BusinessServiceComponent.get_or_none(
                BusinessServiceComponent.business_service == business.id, BusinessServiceComponent.service == service.id,
            )
            if binding and (not component or component.id != binding.local_id):
                raise SyncError("An imported component binding no longer matches its catalog objects")
            if not binding and component and not component.deleted:
                # A locally maintained link is not acquired by this source.
                continue
            if not component or component.deleted:
                component = business_services_repo.create_business_service_component(business.id, {"service": service.id})
                changes.append({"kind": "component", "external_id": external_id, "action": "create",
                                "fields": {"service": service_id, "business_service": business_id}})
            if not binding:
                Binding.create(source=source.id, kind="component", external_id=external_id, local_id=component.id, created=True)
            elif binding.source_id != source.id:
                binding.source = source.id
                binding.owned = True
                binding.save()
                changes.append({"kind": "component", "external_id": external_id, "action": "reconnect", "fields": {}})

    if config.relationship_attribute:
        # Query exclusions / missing objects are not evidence of deletion. Only
        # remove source-created links when both endpoints are in this snapshot.
        for binding in list(Binding.select().where(Binding.source == source.id, Binding.kind == "component", Binding.owned == True)):
            service_id, business_id = binding.external_id.split(":", 1)
            if (binding.external_id in expected_edges or service_id not in locals_by_kind["service"]
                    or business_id not in locals_by_kind["business_service"]):
                continue
            component = BusinessServiceComponent.get_by_id(binding.local_id)
            if (component.service_id != locals_by_kind["service"][service_id].id
                    or component.business_service_id != locals_by_kind["business_service"][business_id].id):
                raise SyncError("An imported component moved outside its original catalog objects")
            if not component.deleted:
                business_services_repo.soft_delete_business_service_component(component.id)
                changes.append({"kind": "component", "external_id": binding.external_id, "action": "remove", "fields": {}})

    from app.services.business_services.status import apply_business_service_status
    for business in locals_by_kind["business_service"].values():
        apply_business_service_status(business)
    return {"changes": changes, "issues": [], "warnings": warnings}


def remove_catalog(source, *, delete_imported):
    """Delete only source-created catalog objects; matched Teams always survive."""
    from app.services.change_intelligence.administration import lock_catalog

    lock_catalog()
    bindings = list(Binding.select().where(Binding.source == source.id, Binding.owned == True, Binding.created == True))
    if delete_imported:
        # Validate all destinations before beginning destructive changes.
        for binding in bindings:
            if binding.kind in MODELS:
                model = MODELS[binding.kind]
                local = model.get_or_none(model.id == binding.local_id)
                if local and not local.deleted:
                    validate_local(source, binding.kind, binding)
        for kind, delete_object in (
            ("business_service", business_services_repo.soft_delete_business_service),
            ("service", service_mutations.soft_delete_service),
        ):
            for binding in bindings:
                if binding.kind == kind:
                    local = MODELS[kind].get_or_none(MODELS[kind].id == binding.local_id)
                    if local and not local.deleted:
                        delete_object(local.id)
        Binding.delete().where(Binding.source == source.id).execute()
    else:
        Binding.update(owned=False).where(Binding.source == source.id).execute()
    source.deleted = True
    source.deleted_at = utc_now()
    source.enabled = False
    source.revision += 1
    source.approved_revision = None
    for field in ("headers_encrypted", "preview_encrypted", "preview_token", "preview_result", "preview_until",
                  "pending_mode", "pending_preview_token", "lease", "lease_until", "current_lease", "current_lease_until"):
        setattr(source, field, None)
    source.save()
