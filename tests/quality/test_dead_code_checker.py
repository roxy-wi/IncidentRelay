"""Regression tests for the public dead-code CI gate."""

import pytest

from tools.check_dead_code import source_files, unused_public_definitions


def _unused(tmp_path, source, callers=""):
    app = tmp_path / "app"
    app.mkdir()
    (app / "example.py").write_text(source, encoding="utf-8")
    (tmp_path / "run.py").write_text(callers, encoding="utf-8")
    return {name for _, name, _ in unused_public_definitions(source_files(tmp_path), app)}


def test_reports_unused_functions_and_classes_including_decorated_helpers(tmp_path):
    assert _unused(tmp_path, (
        "def unused():\n    pass\n"
        "class Unused:\n    pass\n"
        "@cache\ndef cached_but_unused():\n    pass\n"
    )) == {"unused", "Unused", "cached_but_unused"}


def test_preserves_flask_registration_and_called_plugins(tmp_path):
    assert _unused(tmp_path, (
        "@bp.route('/example')\ndef endpoint():\n    pass\n"
        "@bp.post('/event')\ndef receive_event():\n    pass\n"
        "@app.errorhandler(404)\ndef missing(error):\n    pass\n"
        "@app.context_processor\ndef context():\n    pass\n"
        "class Plugin:\n    pass\n"
    ), "from app.example import Plugin\nREGISTRY = {'plugin': Plugin()}\n") == set()


def test_tests_are_callers_but_temporary_checkouts_are_not(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text("from app.example import supported\nsupported()\n")
    stale = tests / ".tmp"
    stale.mkdir()
    (stale / "caller.py").write_text("from app.example import unused\nunused()\n")
    assert _unused(tmp_path, "def supported():\n    pass\ndef unused():\n    pass\n") == {"unused"}


@pytest.mark.parametrize("directory", ["docker", "examples", "docs/examples", "."])
def test_extension_examples_and_entrypoints_are_callers(tmp_path, directory):
    callers = tmp_path / directory
    callers.mkdir(parents=True, exist_ok=True)
    (callers / "provider.py").write_text(
        "from app.example import supported\nsupported()\n", encoding="utf-8",
    )
    assert _unused(tmp_path, "def supported():\n    pass\n") == set()


def test_framework_methods_and_private_helpers_are_outside_public_gate(tmp_path):
    assert _unused(tmp_path, (
        "class Model:\n"
        "    class Meta:\n        table_name = 'example'\n"
        "    def callback(self):\n        pass\n"
        "Model()\n"
        "def _private():\n    pass\n"
    )) == set()


def test_syntax_errors_fail_analysis(tmp_path):
    with pytest.raises(ValueError, match="could not parse"):
        _unused(tmp_path, "def broken(:\n")
