from app.db import init_database
from app.modules.db.models import ServiceSli, ServiceSlo, ServiceSloMeasurement


db = init_database()


def upgrade():
    """Replace response objectives with explicit SLI/SLO tables."""
    db.drop_tables([ServiceSloMeasurement, ServiceSlo, ServiceSli], safe=True)
    db.create_tables([ServiceSli, ServiceSlo, ServiceSloMeasurement], safe=True)


def downgrade():
    db.drop_tables([ServiceSloMeasurement, ServiceSlo, ServiceSli], safe=True)
