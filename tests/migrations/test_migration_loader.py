from types import SimpleNamespace

import pytest

from app.modules.db import migrations


@pytest.mark.parametrize(
    "spec",
    [
        None,
        SimpleNamespace(loader=None),
    ],
)
def test_load_migration_module_rejects_missing_import_spec_or_loader(
    monkeypatch,
    spec,
):
    monkeypatch.setattr(
        migrations.importlib.util,
        "spec_from_file_location",
        lambda *args, **kwargs: spec,
    )

    with pytest.raises(
        migrations.MigrationError,
        match="Could not load migration module 20260818000000_broken",
    ):
        migrations.load_migration_module(
            "/tmp/20260818000000_broken.py"
        )
