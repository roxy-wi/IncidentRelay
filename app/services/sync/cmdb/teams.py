"""Resolve Jira team references within the locked destination catalog."""

from collections import Counter, defaultdict

from app.api.schemas.limits import NAME_MAX_LENGTH, NAME_MIN_LENGTH, SLUG_MAX_LENGTH
from app.modules.db.models import Team
from app.modules.db.transactions import lock_row
from app.services import team_management
from app.services.sync.directory.reconcile import slug


def resolve_teams(source, config, catalog, changes, issues):
    """Return local IDs and identify teams whose database IDs are provisional in preview."""
    teams = {}
    created = set()
    pending = []
    for external in catalog:
        key = external["id"]
        local_id = config.team_matches.get(key)
        if local_id is None and config.create_missing_teams:
            pending.append(external)
            continue
        team = lock_row(Team.select().where(Team.id == local_id)) if local_id else None
        if team is None or team.deleted or not team.active or team.group_id != source.group_id:
            issues.append(f"CMDB team {key}: select an active existing IR team in the destination group")
        else:
            teams[key] = team.id

    if not pending:
        return teams, created
    by_name = defaultdict(list)
    for team in Team.select().where(Team.group == source.group_id, Team.deleted == False):
        by_name[team.name.strip().casefold()].append(team)
    pending_names = Counter(item["name"].strip().casefold() for item in pending)

    for external in pending:
        key, name = external["id"], external["name"].strip()
        normalized = name.casefold()
        candidates = by_name[normalized]
        active = [team for team in candidates if team.active]
        if external.get("name_missing") or not name:
            issues.append(f"CMDB team {key} has no name. Select its IR team explicitly.")
            continue
        if len(active) > 1 or pending_names[normalized] > 1:
            issues.append(f"CMDB team {name!r} (ID {key}) has an ambiguous name. Select its IR team explicitly.")
            continue
        if active:
            team = active[0]
            action, fields = "match", {"team_id": team.id}
        elif candidates:
            issues.append(f"CMDB team {name!r} (ID {key}) matches an inactive team. Select an active IR team.")
            continue
        else:
            if not NAME_MIN_LENGTH <= len(name) <= NAME_MAX_LENGTH:
                issues.append(f"CMDB team {key} needs a name of {NAME_MIN_LENGTH}–{NAME_MAX_LENGTH} characters "
                              "to create an IR team. Select an existing team or update the Jira name.")
                continue
            team_slug = slug(("jira-" + name)[:SLUG_MAX_LENGTH - 13], f"cmdb:{source.id}:{key}")
            if Team.select().where(Team.slug == team_slug).exists():
                issues.append(f"CMDB team {key} cannot use the reserved slug {team_slug!r}. Select an IR team explicitly.")
                continue
            team = team_management.create_team(slug=team_slug, name=name, group_id=source.group_id)
            created.add(key)
            action, fields = "create", {"name": name, "slug": team_slug}
        teams[key] = team.id
        changes.append({"kind": "team", "external_id": key, "label": name, "action": action, "fields": fields})
    return teams, created
