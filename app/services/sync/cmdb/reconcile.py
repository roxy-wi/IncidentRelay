"""Reconcile catalog ownership, business components and technical dependencies."""

import re

from peewee import chunked

from app.modules.common import utc_now
from app.modules.db import business_services_repo
from app.modules.db.models import (
    BusinessService, BusinessServiceComponent, DirectorySyncBinding as Binding,
    DirectorySyncSource as Source, Service, ServiceChannel, ServiceDependency, Team,
)
from app.modules.db.transactions import lock_row
from app.services.service_catalog import mutations as service_mutations
from app.services.sync.cmdb.config import CmdbConfig, is_cmdb
from app.services.sync.cmdb.teams import resolve_teams
from app.services.sync.directory.config import SyncError


MODELS = {"service": Service, "business_service": BusinessService}
LINK_MODELS = {"component": BusinessServiceComponent, "dependency": ServiceDependency}


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
        model = MODELS[kind] if kind in MODELS else LINK_MODELS[kind]
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


def previously_imported_targets(source, external_ids):
    """Resolve referenced services from this source under the catalog lock."""
    targets = {}
    for batch in chunked(external_ids, 500):
        bindings = (Binding.select(Binding.external_id, Service.id, Service.enabled)
                    .join(Service, on=(Binding.local_id == Service.id).alias("service"))
                    .join(Team)
                    .where(Binding.source == source.id, Binding.kind == "service", Binding.owned == True,
                           Binding.external_id.in_(batch), Service.group == source.group_id, Service.deleted == False,
                           Team.group == source.group_id, Team.deleted == False))
        for binding in bindings:
            targets[binding.external_id] = binding.service
    return targets


def reconcile_links(source, kind, pairs, services, targets, changes, warnings, *, previous_targets=None):
    """Resolve declared links and prune only when both endpoints were imported in this run."""
    is_dependency = kind == "dependency"
    model = LINK_MODELS[kind]
    target_field = ServiceDependency.depends_on_service if is_dependency else BusinessServiceComponent.business_service
    expected = set()
    for service_id, target_id in pairs:
        service, target = services.get(service_id), targets.get(target_id)
        if target is None and previous_targets:
            target = previous_targets.get(target_id)
        if is_dependency and service and target is None:
            warnings.append(f"Dependency {service_id} -> {target_id} was skipped: the target is outside the "
                            "current service selection and has no eligible service binding from this source.")
            continue
        if not service or not target:
            label = "Dependency" if is_dependency else "Relationship"
            warnings.append(f"{label} {service_id} -> {target_id} refers to an object outside this import. "
                            "Existing links were retained.")
            continue
        if is_dependency and service.id == target.id:
            warnings.append(f"Service {service_id} cannot depend on itself. This reference was skipped.")
            continue
        external_id = f"{service_id}:{target_id}"
        expected.add(external_id)
        binding = existing_binding(source, kind, external_id)
        link = model.get_or_none(model.service == service.id, target_field == target.id)
        if binding and (not link or link.id != binding.local_id):
            raise SyncError(f"An imported {kind} binding no longer matches its catalog objects")
        if not binding and link and not link.deleted:
            continue  # The existing link is managed locally.
        if not link or link.deleted:
            if is_dependency:
                if not target.enabled:
                    warnings.append(f"Dependency {service_id} -> {target_id} was skipped because the target is disabled.")
                    continue
                link = service_mutations.create_service_dependency(service.id, {"depends_on_service": target.id})
            else:
                link = business_services_repo.create_business_service_component(target.id, {"service": service.id})
            fields = {"service": service_id, target_field.name: target_id}
            if target_id not in targets:
                # Pin the previously imported IR destination in the reviewed plan.
                fields["depends_on_service_ir_id"] = target.id
            changes.append({"kind": kind, "external_id": external_id, "action": "create", "fields": fields})
        if not binding:
            Binding.create(source=source.id, kind=kind, external_id=external_id, local_id=link.id, created=True)
        elif binding.source_id != source.id:
            binding.source = source.id
            binding.owned = True
            binding.save()
            changes.append({"kind": kind, "external_id": external_id, "action": "reconnect", "fields": {}})

    owned = Binding.select().where(Binding.source == source.id, Binding.kind == kind, Binding.owned == True)
    for binding in list(owned):
        service_id, target_id = binding.external_id.split(":", 1)
        if binding.external_id in expected or service_id not in services or target_id not in targets:
            continue
        link = model.get_by_id(binding.local_id)
        if (link.service_id != services[service_id].id
                or getattr(link, target_field.object_id_name) != targets[target_id].id):
            raise SyncError(f"An imported {kind} moved outside its original catalog objects")
        if not link.deleted:
            if is_dependency:
                service_mutations.soft_delete_service_dependency(link.id)
            else:
                business_services_repo.soft_delete_business_service_component(link.id)
            changes.append({"kind": kind, "external_id": binding.external_id, "action": "remove", "fields": {}})
        if is_dependency:
            # A later manual creation restores the same row; it must have a new owner.
            binding.delete_instance()


def reconcile(source, snapshot):
    """Run inside the shared fenced transaction (rolled back when previewing)."""
    from app.services.change_intelligence.administration import lock_catalog

    lock_catalog()
    config = CmdbConfig.model_validate(source.config)
    changes, issues = [], list(snapshot["issues"])
    warnings = list(snapshot.get("warnings", []))
    teams, created_teams = resolve_teams(source, config, snapshot["team_catalog"], changes, issues)
    if issues:
        return {"changes": [], "issues": issues, "warnings": warnings}, {}

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
            if row["team_id"] is not None:
                team_id = teams[row["team_id"]]
            elif local:
                team_id = local.team_id if kind == "service" else local.owner_team_id
            elif kind == "service":
                warnings.append(f"Service {row['key']} ({row['name']}, ID {row['id']}) was skipped because "
                                "a new technical service requires an owner team.")
                continue
            else:
                team_id = None
            values = changes_for(source, row, local, team_id, kind)
            reconnect = binding and binding.source_id != source.id
            if values or reconnect:
                fields = values
                if row["team_id"] in created_teams:
                    # PostgreSQL allocates different team IDs on preview and apply.
                    owner_field = "team" if kind == "service" else "owner_team"
                    fields = {**values, owner_field: {"cmdb_team_id": row["team_id"]}}
                changes.append({"kind": kind, "external_id": row["id"], "label": row["name"],
                                "action": "reconnect" if reconnect else "update" if local else "create", "fields": fields})
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

    services = locals_by_kind["service"]
    if config.relationship_attribute:
        pairs = (
            (row["id"], ref) if config.relationship_side == "services" else (ref, row["id"])
            for row in snapshot[config.relationship_side] for ref in sorted(set(row["references"]))
        )
        reconcile_links(source, "component", pairs, services, locals_by_kind["business_service"], changes, warnings)
    if config.dependency_attribute:
        pairs = (
            (row["id"], ref) for row in snapshot["services"] for ref in sorted(set(row["dependencies"]))
        )
        previous_targets = previously_imported_targets(source, snapshot.get("external_dependency_ids", ()))
        reconcile_links(source, "dependency", pairs, services, services, changes, warnings,
                        previous_targets=previous_targets)

    from app.services.business_services.status import apply_business_service_status
    for business in locals_by_kind["business_service"].values():
        apply_business_service_status(business)
    new_matches = {key: team_id for key, team_id in teams.items() if key not in config.team_matches}
    return {"changes": changes, "issues": [], "warnings": warnings}, new_matches


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
