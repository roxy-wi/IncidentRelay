"""Create Event Orchestration v1 control-plane tables."""

from app.db import init_database
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
)


db = init_database()


def upgrade():
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            OrchestrationExecution,
        ],
        safe=True,
    )


def downgrade():
    db.drop_tables(
        [
            OrchestrationExecution,
            OrchestrationIntakeToken,
            EventOrchestrationRule,
            EventOrchestrationVersion,
            EventOrchestration,
        ],
        safe=True,
    )
