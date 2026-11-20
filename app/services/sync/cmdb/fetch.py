"""Read complete Assets snapshots without holding database transactions."""

from app.services.sync.directory.config import SyncError


def selected_record(record, definitions, config, kind):
    """Discard avatars, nested profiles and unselected attributes between pages."""
    selectors = {value for field, value in getattr(config, kind).model_dump().items()
                 if field.endswith("_attribute") and value}
    if kind == config.relationship_side and config.relationship_attribute:
        selectors.add(config.relationship_attribute)
    attributes = []
    for attribute in record["attributes"]:
        if not isinstance(attribute, dict):
            raise SyncError("Jira Assets returned an invalid attribute")
        key = object_id(attribute.get("objectTypeAttributeId"))
        if key not in selectors and definitions.get(key, {}).get("name") not in selectors:
            continue
        values = attribute.get("objectAttributeValues")
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            raise SyncError("Jira Assets returned invalid attribute values")
        compact_values = []
        for value in values:
            compact = {"value": value.get("value")}
            for field, keys in (("referencedObject", ("id", "label", "name")), ("status", ("name",))):
                if isinstance(value.get(field), dict):
                    compact[field] = {key: value[field].get(key) for key in keys}
            compact_values.append(compact)
        attributes.append({"objectTypeAttributeId": key, "objectAttributeValues": compact_values})
    return {**{key: record.get(key) for key in ("id", "label", "objectKey", "archived")}, "attributes": attributes}


def object_id(value):
    """Normalize IDs without accepting booleans, floats or arbitrary response text."""
    if (isinstance(value, bool) or not isinstance(value, (int, str)) or len(str(value)) > 20
            or not str(value).isdecimal() or int(value) < 1):
        raise SyncError("Jira Assets returned an invalid object or attribute ID")
    return str(int(value))


def read_collection(client, kind):
    """Honor Jira's total count even when the server caps the requested page size."""
    records, definitions, seen = [], {}, set()
    expected_total = None
    for page in range(1, client.config.max_pages + 1):
        response = client.request(kind, {}, {
            "page": page, "resultPerPage": client.config.page_size,
            # AQL is opaque user input, not a directory request template.
            client.config.query_parameter: getattr(client.config, kind).query,
        })
        if not isinstance(response, dict) or not isinstance(response.get("objectEntries"), list):
            raise SyncError(f"{kind}: expected an Assets objectEntries array")
        total = response.get("totalFilterCount")
        if type(total) is not int or not 0 <= total <= 100000:
            raise SyncError(f"{kind}: missing or invalid totalFilterCount; cannot verify a complete import")
        if response.get("pageNumber", page) != page or (expected_total is not None and total != expected_total):
            raise SyncError(f"{kind}: pagination changed during import; retry the preview")
        expected_total = total
        attributes = response.get("objectTypeAttributes", [])
        if not isinstance(attributes, list):
            raise SyncError(f"{kind}: invalid attribute definitions")
        for definition in attributes:
            if not isinstance(definition, dict) or not isinstance(definition.get("name"), str):
                raise SyncError(f"{kind}: invalid attribute definition")
            key = object_id(definition.get("id"))
            compact = {"id": key, "name": definition["name"], "type": definition.get("type"),
                       "reference_type_id": definition.get("referenceObjectTypeId")}
            if key in definitions and definitions[key] != compact:
                raise SyncError(f"{kind}: attribute definitions changed during import")
            definitions[key] = compact
        batch = response["objectEntries"]
        for record in batch:
            if not isinstance(record, dict):
                raise SyncError(f"{kind}: expected an Assets object")
            key = object_id(record.get("id"))
            if key in seen:
                raise SyncError(f"{kind}: repeated object ID in pagination; no changes were applied")
            if not isinstance(record.get("attributes"), list):
                raise SyncError(f"{kind}: attributes are missing; enable includeAttributes")
            seen.add(key)
            records.append(selected_record(record, definitions, client.config, kind))
        if len(records) == total:
            return records, definitions
        if not batch or len(records) > total:
            raise SyncError(f"{kind}: incomplete or inconsistent pagination; no changes were applied")
    raise SyncError(f"{kind}: pagination limit reached; no changes were applied")


def attribute_values(record, definitions, selector):
    """Resolve a configured attribute using ID or its exact schema name."""
    if not selector:
        return []
    matches = []
    for attribute in record["attributes"]:
        if not isinstance(attribute, dict):
            raise SyncError("Jira Assets returned an invalid attribute")
        key = object_id(attribute.get("objectTypeAttributeId"))
        if key == selector or definitions.get(key, {}).get("name") == selector:
            matches.append(attribute)
    if len(matches) > 1:
        raise SyncError("Attribute name is ambiguous; select its numeric ID")
    if not matches:
        return []
    values = matches[0].get("objectAttributeValues")
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise SyncError("Jira Assets returned invalid attribute values")
    return values


def scalar(record, definitions, selector):
    """Read text, object labels or status names without guessing their semantics."""
    values = attribute_values(record, definitions, selector)
    if len(values) > 1:
        raise SyncError("A scalar catalog field contains multiple values; select a single-value attribute")
    if not values:
        return None
    value = values[0]
    if isinstance(value.get("referencedObject"), dict):
        result = value["referencedObject"].get("label")
    elif isinstance(value.get("status"), dict):
        result = value["status"].get("name")
    else:
        result = value.get("value")
    if result is None:
        return None
    if not isinstance(result, (str, int, float, bool)):
        raise SyncError("Jira Assets returned a non-scalar field value")
    return str(result).strip()


def references(record, definitions, selector):
    """Return stable IDs and display names for explicitly selected references."""
    result = []
    for value in attribute_values(record, definitions, selector):
        ref = value.get("referencedObject")
        if not isinstance(ref, dict):
            raise SyncError("The team or relationship field must reference Assets objects")
        result.append({"id": object_id(ref.get("id")), "name": str(ref.get("label") or ref.get("name") or ref["id"])[:255]})
    return result


def fetch_snapshot(client, *, inspect_only=False):
    """Normalize only selected catalog fields; never retain arbitrary CMDB profiles."""
    snapshot = {"services": [], "business_services": [], "attributes": {}, "team_catalog": [], "issues": []}
    teams = {}
    for kind in ("services", "business_services"):
        records, definitions = read_collection(client, kind)
        snapshot["attributes"][kind] = sorted(definitions.values(), key=lambda item: (item["name"], item["id"]))
        selection = getattr(client.config, kind)
        selectors = {field: value for field, value in selection.model_dump().items() if field.endswith("_attribute") and value}
        if kind == client.config.relationship_side and client.config.relationship_attribute:
            selectors["relationship_attribute"] = client.config.relationship_attribute
        known_names = {definition["name"] for definition in definitions.values()}
        for field, selector in selectors.items():
            if records and selector not in definitions and selector not in known_names:
                snapshot["issues"].append(f"{kind}: configured {field} was not found in the returned schema; load and select the field again")
        for record in records:
            if record.get("archived") is True:
                continue
            key = object_id(record["id"])
            try:
                owners = references(record, definitions, selection.owner_team_attribute)
            except SyncError as error:
                if not inspect_only:
                    raise
                # Discovery must expose the schema needed to fix a bad mapping.
                # Preserve an actionable issue rather than discarding the error.
                snapshot["issues"].append(f"{kind} object {key}: {error}")
                owners = []
            for owner in owners:
                teams[owner["id"]] = owner
            if len(owners) != 1:
                snapshot["issues"].append(f"{kind} object {key}: select a team field containing exactly one CMDB team")
            if inspect_only:
                snapshot[kind].append({"id": key})
                continue
            name = scalar(record, definitions, selection.name_attribute) if selection.name_attribute else record.get("label")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
                raise SyncError(f"{kind}: object {key} has no usable name (maximum 255 characters)")
            description = scalar(record, definitions, selection.description_attribute)
            if not description:
                description = scalar(record, definitions, selection.fallback_description_attribute)
            if description and len(description) > 5000:
                raise SyncError(f"{kind}: object {key} description exceeds 5000 characters")
            row = {"id": key, "key": str(record.get("objectKey") or key), "name": name.strip(),
                   "team_id": owners[0]["id"] if len(owners) == 1 else None, "fields": {}, "references": []}
            if selection.description_attribute or selection.fallback_description_attribute:
                row["fields"]["description"] = description
            for field, mapping in (("environment", client.config.environment_values),
                                   ("criticality", client.config.criticality_values if kind == "services"
                                    else client.config.business_criticality_values)):
                selector = getattr(selection, field + "_attribute")
                if field == "environment" and kind != "services":
                    continue
                if selector:
                    value = scalar(record, definitions, selector)
                    if value is not None:
                        mapped = mapping.get(value)
                        if mapped is None:
                            snapshot["issues"].append(f"{kind} object {key}: configure a mapping for {field} value {value[:80]!r}")
                        else:
                            row["fields"][field] = mapped
            row["cmdb_status"] = scalar(record, definitions, selection.status_attribute)
            if kind == client.config.relationship_side:
                row["references"] = [ref["id"] for ref in references(record, definitions, client.config.relationship_attribute)]
            snapshot[kind].append(row)
    if {row["id"] for row in snapshot["services"]} & {row["id"] for row in snapshot["business_services"]}:
        raise SyncError("Service and business-service queries overlap; select disjoint object sets")
    snapshot["team_catalog"] = sorted(teams.values(), key=lambda team: (team["name"], team["id"]))
    return snapshot
