import inspect
import sys

from app.db import init_database
from app.modules.db.models import BaseModel
import app.modules.db.models as models


def model_classes():
    """
    Return all Peewee model classes.
    """

    result = []

    for _, obj in vars(models).items():
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            result.append(obj)

    return sorted(result, key=lambda model: model._meta.table_name)


def main():
    """
    Check that all model tables and model columns exist in the configured DB.
    """

    db = init_database()
    tables = set(db.get_tables())
    ok = True

    for model in model_classes():
        table = model._meta.table_name

        if table not in tables:
            print(f"MISSING TABLE: {table} ({model.__name__})")
            ok = False
            continue

        db_columns = {column.name for column in db.get_columns(table)}
        model_columns = {field.column_name for field in model._meta.sorted_fields}
        missing_columns = sorted(model_columns - db_columns)

        if missing_columns:
            print(f"MISSING COLUMNS: {table}: {', '.join(missing_columns)}")
            ok = False

    if ok:
        print("Schema check OK: all model tables and columns exist.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
