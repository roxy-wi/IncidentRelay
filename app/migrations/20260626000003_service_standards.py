from app.db import init_database
from app.modules.db.models import ServiceReadinessCheckResult, ServiceReadinessEvaluation, ServiceReadinessState, ServiceStandard, ServiceStandardCheck


db = init_database()


def upgrade():
    db.create_tables(
        [
            ServiceStandard,
            ServiceStandardCheck,
            ServiceReadinessEvaluation,
            ServiceReadinessCheckResult,
            ServiceReadinessState
         ],
        safe=True
    )


def downgrade():
    db.drop_tables(
        [
            ServiceReadinessState,
            ServiceReadinessCheckResult,
            ServiceReadinessEvaluation,
            ServiceStandardCheck,
            ServiceStandard
         ],
        safe=True
    )
