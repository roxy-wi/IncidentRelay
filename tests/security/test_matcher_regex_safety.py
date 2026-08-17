from app.services.routing.matcher import matchers


def test_matcher_regex_timeout_fails_closed(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError("regex took too long")

    monkeypatch.setattr(matchers.regex, "search", timeout)

    assert matchers.safe_regex_search("(a+)+$", "a" * 1000 + "!") is False


def test_matcher_regex_rejects_oversized_pattern_before_execution(monkeypatch):
    called = []
    monkeypatch.setattr(
        matchers.regex,
        "search",
        lambda *args, **kwargs: called.append(True),
    )

    assert matchers.safe_regex_search(
        "a" * (matchers.MATCHER_REGEX_MAX_PATTERN_LENGTH + 1),
        "a",
    ) is False
    assert called == []


def test_match_alert_uses_bounded_regex_helper(monkeypatch):
    calls = []

    def safe(pattern, value):
        calls.append((pattern, value))
        return True

    monkeypatch.setattr(matchers, "safe_regex_search", safe)

    assert matchers.match_alert(
        {"title": "DiskFull", "labels": {}},
        {"title_regex": "Disk.*"},
    ) is True
    assert calls == [("Disk.*", "DiskFull")]
