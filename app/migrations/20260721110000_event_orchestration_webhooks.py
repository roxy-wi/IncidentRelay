"""Add asynchronous outbound webhook actions for Event Orchestration."""

from app.db import init_database
from app.migrations.introspection import table_exists
from app.modules.db.models import AutomationExecution, OrchestrationWebhookAction


db = init_database()
MODELS = (OrchestrationWebhookAction, AutomationExecution)


def upgrade():
    db.create_tables(list(MODELS), safe=True)


def downgrade():
    for model in reversed(MODELS):
        if table_exists(db, model._meta.table_name):
            db.drop_tables([model], safe=True)
