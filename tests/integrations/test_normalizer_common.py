from app.services.integrations.normalizers.common import (
    canonical_label_key,
    clean_string,
    first_present,
    normalize_event_link,
    normalize_label_value,
    severity_from_priority,
    stable_labels,
)


def test_clean_string_is_shared_by_event_link_normalization():
    assert clean_string("  value  ") == "value"
    assert clean_string(0) == "0"
    assert clean_string("   ") is None
    assert normalize_event_link("  https://example.com/alert  ") == (
        "https://example.com/alert"
    )


def test_first_present_preserves_falsey_values():
    assert first_present(None, " ", 0, 1) == 0
    assert first_present(None, False, True) is False
    assert first_present(None, " ") is None


def test_canonical_label_key_normalizes_external_names():
    assert canonical_label_key(" Region / Availability-Zone ") == (
        "region_availability_zone"
    )
    assert canonical_label_key("___") == ""


def test_normalize_label_value_keeps_scalars_and_serializes_objects():
    assert normalize_label_value(" value ") == " value "
    assert normalize_label_value(" ") == " "
    assert normalize_label_value(False) is False
    assert normalize_label_value({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


def test_stable_labels_excludes_volatile_keys_and_sorts_output():
    labels = {
        "status": "down",
        "service": "payments",
        "event_link": "https://example.com",
    }

    assert list(stable_labels(labels, exclude={"event_link", "status"})) == [
        "service"
    ]


def test_severity_from_priority_maps_common_monitor_priorities():
    assert severity_from_priority(" P1 ") == "critical"
    assert severity_from_priority("p3") == "medium"
    assert severity_from_priority("unknown") is None
    assert severity_from_priority(None) is None
