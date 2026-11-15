"""Local editing of imported intervals through the existing rotation editor."""

import uuid

from pydantic import Field

from app.modules.db.models import DirectorySyncBinding as Binding, DirectorySyncShift as Shift, User
from app.services.directory_sync.config import StrictModel, SyncError
from app.services.directory_sync.fetch import instant, iso
from app.services.directory_sync.runtime import source_for


class ReplacementInput(StrictModel):
    id: str = Field(min_length=1, max_length=255)
    user_id: int = Field(ge=1)
    start: str
    end: str
    precedence: int
    inactive: bool = False


class ShiftInput(StrictModel):
    user_id: int = Field(ge=1)
    start: str
    end: str
    title: str = Field(default="", max_length=255)
    unavailable: bool = False
    replacements: list[ReplacementInput] = Field(default_factory=list)


def serialize_shift(shift):
    return {"id": shift.id, "external_id": shift.external_id, "user_id": shift.user_id,
            "start": iso(shift.starts_at), "end": iso(shift.ends_at), "title": shift.title,
            "unavailable": shift.unavailable,
            "replacements": [{**item, "precedence": str(item["precedence"])} for item in shift.replacements]}


def edit_shift(rotation, payload, shift=None):
    source = source_for("rotation", rotation.id)
    if not source or not source.config.get("editable"):
        raise SyncError("Imported schedule is read-only")
    start, end = instant(payload.start), instant(payload.end)
    if start >= end:
        raise SyncError("Shift end must follow its start")
    user_ids = {payload.user_id, *(item.user_id for item in payload.replacements)}
    allowed = Binding.select(Binding.local_id).where(Binding.source == source.id, Binding.kind == "user")
    if User.select().where(User.id.in_(allowed), User.id.in_(user_ids), User.deleted == False).count() != len(user_ids):
        raise SyncError("Select people imported by this source")
    for item in payload.replacements:
        if not start <= instant(item.start) < instant(item.end) <= end:
            raise SyncError("Replacement must lie inside its shift")
    if len({item.id for item in payload.replacements}) != len(payload.replacements):
        raise SyncError("Replacement IDs must be unique")
    values = {"user": payload.user_id, "starts_at": start, "ends_at": end, "title": payload.title,
              "unavailable": payload.unavailable, "replacements": [item.model_dump() for item in payload.replacements],
              "local_override": True,
              "local_from": min(start, shift.local_from or shift.starts_at) if shift else start,
              "local_until": max(end, shift.local_until or shift.ends_at) if shift else end}
    if shift:
        Shift.update(**values).where(Shift.id == shift.id).execute()
        return Shift.get_by_id(shift.id)
    return Shift.create(source=source, rotation=rotation, external_id="local:" + str(uuid.uuid4()), **values)
