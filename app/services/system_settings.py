"""Read installation-wide settings and audit authorized partial updates."""

from app.api.schemas.system_settings import SystemSettingsUpdate
from app.modules.db.models import SystemSettings, User
from app.modules.db.transactions import lock_row, write_transaction
from app.services.audit import record_audit
from app.services.admin_tokens import lock_admin_api_token
from app.services.rbac import current_api_token


class SystemSettingsAccessDenied(PermissionError):
    """The actor is no longer an active global administrator."""


class InvalidRetryWindow(ValueError):
    """The base delay exceeds the maximum delay in the resulting settings."""


def get_settings() -> SystemSettings:
    """Read the committed singleton on each request or scheduler tick."""
    return SystemSettings.get_by_id(1)


def update_settings(payload: SystemSettingsUpdate, *, actor_id: int) -> SystemSettings:
    """Recheck the actor under lock and commit the changes and audit together."""
    with write_transaction():
        actor = lock_row(User.select().where(User.id == actor_id))
        if actor is None or not actor.active or actor.deleted or not actor.is_admin:
            raise SystemSettingsAccessDenied()
        try:
            lock_admin_api_token(actor_id, "system-settings:write")
        except PermissionError as error:
            raise SystemSettingsAccessDenied() from error
        row = lock_row(SystemSettings.select().where(SystemSettings.id == 1))
        if row is None:
            raise RuntimeError("System settings are missing; run database migrations")
        changes = {}
        for name, after in payload.model_dump(exclude_unset=True).items():
            before = getattr(row, name)
            if before != after:
                changes[name] = {"before": before, "after": after}
                setattr(row, name, after)
        if row.change_worker_retry_base_seconds > row.change_worker_retry_max_seconds:
            raise InvalidRetryWindow("Base retry delay must not exceed the maximum retry delay")
        if changes:
            row.save(only=[getattr(SystemSettings, name) for name in changes])
            record_audit(
                "system_settings.updated",
                object_type="system_settings",
                object_id=row.id,
                user_id=actor_id,
                api_token_id=getattr(current_api_token(), "id", None),
                data={"changes": changes},
            )
        return row
