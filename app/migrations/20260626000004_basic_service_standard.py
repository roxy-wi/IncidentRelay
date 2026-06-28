from app.db import init_database
from app.modules.db.models import Group, Service
from app.services.service_catalog.presets import ensure_basic_operational_standard
from app.services.service_catalog.readiness import evaluate_service_readiness


db = init_database()


def upgrade():
    for group in Group.select():
        ensure_basic_operational_standard(group)

    for service in Service.select().where(Service.deleted == False):
        evaluate_service_readiness(service, trigger="basic_standard_migration")


def downgrade():
    pass
