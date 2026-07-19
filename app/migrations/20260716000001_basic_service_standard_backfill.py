from app.db import init_database
from app.modules.db.models import Group, Service
from app.services.service_catalog.presets import ensure_basic_operational_standard
from app.services.service_catalog.readiness import evaluate_service_readiness


db = init_database()


def upgrade():
    """Restore the built-in standard for every existing non-deleted group."""

    for group in Group.select().where(Group.deleted == False):
        ensure_basic_operational_standard(group)

    for service in Service.select().where(Service.deleted == False):
        evaluate_service_readiness(
            service,
            trigger="basic_standard_backfill",
        )


def downgrade():
    # The preset is user-editable and may already be referenced by readiness
    # evaluations, so it is intentionally not removed during rollback.
    pass
