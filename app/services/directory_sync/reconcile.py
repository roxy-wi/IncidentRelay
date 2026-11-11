"""Transactional, ownership-aware reconciliation of a validated API snapshot."""

import hashlib
import re
from datetime import datetime

from peewee import fn

from app.modules.common import utc_now
from app.modules.db import rotations_repo, teams_repo, users_repo
from app.modules.db.models import (
    DirectorySyncBinding as Binding, DirectorySyncShift as Shift,
    Rotation, Team, TeamUser, User, UserGroup,
)
from app.services.directory_sync.config import SyncConfig, SyncError
from app.services.directory_sync.fetch import instant


def slug(value, suffix):
    stem = re.sub(r"[^a-z0-9_-]+", "-", str(value).lower()).strip("-")[:100] or "imported"
    return f"{stem}-{hashlib.sha256(suffix.encode()).hexdigest()[:12]}"


def shared_user(user_id, group_id):
    """An integration never owns a profile used outside its destination group."""
    return UserGroup.select().where(
        UserGroup.user == user_id, UserGroup.group != group_id, UserGroup.active == True,
    ).exists()


def reconcile(source, snapshot):
    """Apply inside the caller's transaction; preview rolls this transaction back."""
    config = SyncConfig.model_validate(source.config)
    bindings = {(row.kind, row.external_id): row for row in Binding.select().where(Binding.source == source.id)}
    seen, changes = set(), []
    users, rotations = {}, {}
    labels = {("user", item["id"]): item.get("name") or item["email"] for item in snapshot["users"]}
    labels.update({("group_member", item["id"]): item.get("name") or item["email"] for item in snapshot["users"]})
    for team_data in snapshot["teams"]:
        labels[("team", team_data["id"])] = team_data["name"]
        for schedule in team_data["schedules"]:
            labels[("rotation", schedule["id"])] = schedule["name"]
        for member in set(team_data["members"] + ([team_data["responsible"]] if team_data["responsible"] else [])):
            labels[("team_member", identity_key(team_data["id"], member))] = team_data["name"] + " / " + labels[("user", member)]

    def record(kind, key, action, fields=None):
        changes.append({"kind": kind, "external_id": key, "label": labels.get((kind, key), key),
                        "action": action, "fields": fields or {}})

    def scalar(value):
        return value.isoformat() + "Z" if isinstance(value, datetime) else value

    def bind(kind, key, local, *, owned=True, created=False):
        seen.add((kind, key))
        binding = bindings.get((kind, key))
        if binding:
            if binding.local_id != local.id:
                raise SyncError("An external identity cannot be rebound to another local object")
            if not binding.present:
                binding.present = True
                binding.save()
            return binding
        binding = Binding.create(source=source, kind=kind, external_id=key, local_id=local.id,
                                 owned=owned, created=created)
        bindings[(kind, key)] = binding
        return binding

    def update(row, kind, key, values):
        diff = {field: value for field, value in values.items() if getattr(row, field) != value}
        if diff:
            before = {field: {"before": scalar(getattr(row, field)), "after": scalar(value)} for field, value in diff.items()}
            for field, value in diff.items():
                setattr(row, field, value)
            row.save(only=[getattr(type(row), field) for field in diff])
            record(kind, key, "update", before)

    for data in snapshot["users"]:
        key = data["id"]
        binding = bindings.get(("user", key))
        user = User.get_or_none(User.id == binding.local_id) if binding else None
        matches = list(User.select().where(fn.LOWER(fn.TRIM(User.email)) == data["email"]))
        if len(matches) > 1 or (user and any(row.id != user.id for row in matches)):
            raise SyncError("Email identity conflict; resolve duplicate users before syncing")
        if not binding and matches:
            user = matches[0]
        if user and user.deleted:
            raise SyncError("A matched user was deleted; restore or remap it explicitly")
        created = user is None
        if created:
            username = str(data.get("username") or data["email"].split("@", 1)[0]).strip()[:200]
            if User.select().where(User.username == username).exists():
                username = slug(username, f"{source.id}:{key}")
            user = users_repo.create_user(username=username, email=data["email"],
                                          display_name=data.get("name") or username,
                                          phone=data.get("phone"), password_hash=None,
                                          active=not data["inactive"], is_admin=False)
            record("user", key, "create", {"username": username, "email": data["email"]})
        binding = bind("user", key, user, owned=created, created=created)
        # Existing accounts (including administrators) are linked, never overwritten.
        # A once-private imported account may since have joined another group.
        if binding.created and not user.is_admin and not shared_user(user.id, source.group_id):
            values = {"email": data["email"], "active": not data["inactive"]}
            for external, local in (("name", "display_name"), ("phone", "phone")):
                if external in data:
                    values[local] = data[external]
            update(user, "user", key, values)
        users[key] = user

    def membership(model, kind, key, **values):
        identity = {field: value for field, value in values.items() if field not in {"role", "active"}}
        query = model.select()
        for field, value in identity.items():
            query = query.where(getattr(model, field) == value)
        row = query.first()
        created = row is None
        binding = bindings.get((kind, key))
        if created:
            row = model.create(**values)
            if binding:
                # Team deletion removes membership rows. Reappearance recreates
                # that relationship; PostgreSQL does not reuse its old row ID.
                binding.local_id = row.id
                binding.save(only=[Binding.local_id])
            record(kind, key, "create", {"role": values["role"], "active": values["active"]})
        elif binding and binding.owned:
            update(row, kind, key, {"role": values["role"], "active": values["active"]})
        bind(kind, key, row, owned=created, created=created)

    if config.membership_authority == "sync":
        for data in snapshot["users"]:
            user = users[data["id"]]
            membership(UserGroup, "group_member", data["id"], user=user.id, group=source.group_id,
                       role=config.group_role, active=user.active and not data["inactive"])

    for data in snapshot["teams"]:
        key = data["id"]
        binding = bindings.get(("team", key))
        team = Team.get_or_none(Team.id == binding.local_id) if binding else None
        if binding and config.team_matches.get(key, binding.local_id) != binding.local_id:
            raise SyncError("An imported team already has a stable local match; it cannot be rebound")
        if not binding:
            matched_id = config.team_matches.get(key)
            if matched_id:
                team = Team.get_or_none(Team.id == matched_id, Team.group == source.group_id, Team.deleted == False)
                if not team:
                    raise SyncError("Team mapping must target an existing team in the destination group")
            else:
                matches = list(Team.select().where(Team.group == source.group_id,
                                                   Team.name == data["name"], Team.deleted == False))
                if len(matches) > 1:
                    raise SyncError("Several local teams have this name; choose an explicit team mapping")
                team = matches[0] if matches else None
        if team and team.group_id != source.group_id:
            raise SyncError("A managed team has moved outside the destination group")
        if team and Binding.select().where(Binding.kind == "team", Binding.local_id == team.id,
                                           Binding.source != source.id, Binding.owned == True).exists():
            raise SyncError("Team is managed by another synchronization source")
        created = team is None
        if created:
            team = teams_repo.create_team(slug=slug(data["name"], f"{source.id}:{key}"),
                                          name=data["name"], description=data.get("description"),
                                          group_id=source.group_id, active=data["enabled"])
            record("team", key, "create", {"name": data["name"]})
        binding = bind("team", key, team, owned=created or config.overwrite_existing, created=created)
        if not binding.created and binding.owned != config.overwrite_existing:
            binding.owned = config.overwrite_existing
            binding.save()
        if not binding.owned:
            for existing_key, existing_binding in bindings.items():
                model = Rotation if existing_binding.kind == "rotation" else TeamUser if existing_binding.kind == "team_member" else None
                if model and model.select().where(model.id == existing_binding.local_id, model.team == team.id).exists():
                    seen.add(existing_key)
            record("team", key, "skip", {"reason": "Existing team is not managed"})
            continue
        # The complete snapshot restores managed objects that reappear upstream.
        update(team, "team", key, {"name": data["name"], "description": data.get("description"),
                                   "active": data["enabled"], "deleted": False, "deleted_at": None})
        if config.membership_authority == "sync":
            for user_key in sorted(set(data["members"] + ([data["responsible"]] if data["responsible"] else []))):
                user = users[user_key]
                external_user = next(item for item in snapshot["users"] if item["id"] == user_key)
                membership(TeamUser, "team_member", identity_key(key, user_key),
                           team=team.id, user=user.id,
                           role=config.responsible_role if user_key == data["responsible"] else config.member_role,
                           active=user.active and not external_user["inactive"])
        for schedule in data["schedules"]:
            skey = schedule["id"]
            rb = bindings.get(("rotation", skey))
            rotation = Rotation.get_or_none(Rotation.id == rb.local_id) if rb else None
            if rotation and rotation.team_id != team.id:
                raise SyncError("A schedule cannot change its team implicitly")
            if rotation is None:
                rotation = Rotation.create(team=team, name=schedule["name"],
                                           start_at=instant(snapshot["from"]), timezone=schedule["timezone"],
                                           enabled=data["enabled"])
                record("rotation", skey, "create", {"name": schedule["name"]})
            bind("rotation", skey, rotation, created=rb is None)
            update(rotation, "rotation", skey, {"name": schedule["name"], "timezone": schedule["timezone"],
                                                "enabled": data["enabled"], "deleted": False, "deleted_at": None})
            rotations[skey] = rotation
        for shift in data["shifts"]:
            old = Shift.get_or_none(Shift.source == source.id, Shift.external_id == shift["id"])
            replacements = [{**item, "user_id": users[item["user_id"]].id} for item in shift["replacements"]]
            if old:
                # API replacements are window-filtered. Retain those outside this
                # successful window, including on a shift crossing its boundary.
                ids = {item["id"] for item in replacements}
                replacements += [item for item in old.replacements if item["id"] not in ids
                                 and (instant(item["end"]) <= instant(snapshot["from"])
                                      or instant(item["start"]) >= instant(snapshot["to"]))]
            values = {"rotation_id": rotations[shift["schedule_id"]].id,
                      "user_id": users[shift["user_id"]].id,
                      "starts_at": instant(shift["start"]), "ends_at": instant(shift["end"]),
                      "title": str(shift.get("title") or "")[:255],
                      "unavailable": shift["unavailable"], "replacements": replacements,
                      "local_override": False, "local_from": None, "local_until": None, "deleted": False}
            if old is None:
                Shift.create(source=source, external_id=shift["id"], **values)
                record("shift", shift["id"], "create", {"schedule": shift["schedule_id"],
                                                        "person": labels[("user", shift["user_id"])],
                                                        "start": shift["start"], "end": shift["end"],
                                                        "replacements": len(shift["replacements"])})
            elif any(getattr(old, field) != value for field, value in values.items()):
                before = {field: str(getattr(old, field)) for field in values}
                Shift.update(**values).where(Shift.id == old.id).execute()
                record("shift", shift["id"], "update", {"before": before})

    if config.delete_missing:
        shift_ids = {s["id"] for team in snapshot["teams"] for s in team["shifts"]}
        managed_rotations = list(rotations.values())
        for old in Shift.select().where(Shift.source == source.id,
                                         Shift.rotation.in_([r.id for r in managed_rotations]),
                                         Shift.starts_at < instant(snapshot["to"]),
                                         Shift.ends_at > instant(snapshot["from"])):
            if old.external_id not in shift_ids:
                before = {"start": old.starts_at.isoformat(), "end": old.ends_at.isoformat(), "user_id": old.user_id}
                old.delete_instance()
                record("shift", old.external_id, "delete", before)
        for key, binding in sorted(bindings.items(), key=lambda pair: pair[0][0] == "team"):
            if key in seen or not binding.owned or not binding.present:
                continue
            kind, external_id = key
            if kind in {"group_member", "team_member"}:
                if config.membership_authority != "sync":
                    continue
                model = UserGroup if kind == "group_member" else TeamUser
                # Do not remove access still managed by another source.
                if not Binding.select().where(Binding.kind == kind, Binding.local_id == binding.local_id,
                                               Binding.source != source.id, Binding.present == True).exists():
                    model.update(active=False).where(model.id == binding.local_id).execute()
            elif kind == "rotation":
                if Rotation.select().where(Rotation.id == binding.local_id, Rotation.deleted == False).exists():
                    rotations_repo.soft_delete_rotation(binding.local_id)
            elif kind == "team":
                if Team.select().where(Team.id == binding.local_id, Team.deleted == False).exists():
                    teams_repo.soft_delete_team(binding.local_id)
            elif kind == "user":
                # Global accounts and login identities survive departure from a team.
                binding.present = False
                binding.save()
                continue
            binding.present = False
            binding.save()
            record(kind, external_id, "delete")
    return changes


def identity_key(team_id, user_id):
    """Unambiguous bounded membership identity, even when IDs contain separators."""
    return hashlib.sha256(f"{len(team_id)}:{team_id}{user_id}".encode()).hexdigest()
