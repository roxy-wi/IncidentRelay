"""Benchmark-only A/B switch for compiled lookup SQL; never caches row data."""
import os

from peewee import Model

from app import create_app as application_factory
from app.modules.db.models import BaseModel

_COMPILED_GET = BaseModel.__dict__["get"]
_COMPILED_SAVE = BaseModel.__dict__.get("save", Model.save)


def create_app(log_role=None):
    if os.environ.get("BENCH_DISABLE_COMPILED_LOOKUPS") == "1":
        BaseModel.get = classmethod(Model.get.__func__)
    else:
        BaseModel.get = _COMPILED_GET
    BaseModel.save = Model.save if os.environ.get("BENCH_DISABLE_COMPILED_WRITES") == "1" else _COMPILED_SAVE
    return application_factory(log_role=log_role)
