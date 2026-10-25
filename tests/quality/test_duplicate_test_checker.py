"""Tests for the static duplicate-test guard."""

from tools.check_duplicate_tests import duplicates


def test_identical_tests_in_different_files_are_reported(tmp_path):
    first = tmp_path / "test_first.py"
    second = tmp_path / "test_second.py"
    for path in (first, second):
        path.write_text("def test_example():\n    assert 1 + 1 == 2\n")
    matches = duplicates(tmp_path)
    assert len(matches) == 1
    assert {path for path, _, _ in matches[0]} == {first, second}


def test_different_assertions_are_not_treated_as_duplicates(tmp_path):
    (tmp_path / "test_first.py").write_text("def test_example():\n    assert True\n")
    (tmp_path / "test_second.py").write_text("def test_example():\n    assert False\n")
    assert duplicates(tmp_path) == []


def test_same_file_is_not_reported_as_cross_file_duplication(tmp_path):
    (tmp_path / "test_first.py").write_text(
        "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n"
    )
    assert duplicates(tmp_path) == []
