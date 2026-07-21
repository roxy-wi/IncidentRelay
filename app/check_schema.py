import inspect
import sys

from app.db import init_database
from app.migrations.introspection import get_columns, get_tables
from app.modules.db.models import BaseModel
import app.modules.db.models as models


ABSTRACT_MODEL_NAMES = {
    "SoftDeleteModel",
}


def model_classes():
    """
    Return concrete Peewee model classes only.
    """
    result = []

    for _, obj in vars(models).items():
        if not inspect.isclass(obj):
            continue

        if not issubclass(obj, BaseModel):
            continue

        if obj is BaseModel:
            continue

        if obj.__name__ in ABSTRACT_MODEL_NAMES:
            continue

        result.append(obj)

    return sorted(result, key=lambda model: model._meta.table_name)


def main():
    """
    Check that all concrete model tables and model columns exist
    in the configured DB.
    """
    db = init_database()
    db.connect(reuse_if_open=True)
    tables = set(get_tables(db))
    ok = True

    for model in model_classes():
        table = model._meta.table_name

        if table not in tables:
            print(f"MISSING TABLE: {table} ({model.__name__})")
            ok = False
            continue

        db_columns = {column.name for column in get_columns(db, table)}
        model_columns = {field.column_name for field in model._meta.sorted_fields}
        missing_columns = sorted(model_columns - db_columns)

        if missing_columns:
            print(f"MISSING COLUMNS: {table}: {', '.join(missing_columns)}")
            ok = False

    if not db.is_closed():
        db.close()

    if ok:
        print("Schema check OK: all model tables and columns exist.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
