from app.services.payloads import payload_to_dict


class _Payload:
    def __init__(self):
        self.calls = []

    def model_dump(self, **kwargs):
        self.calls.append(kwargs)
        return {"name": "demo"}


def test_payload_to_dict_uses_pydantic_exclude_unset():
    payload = _Payload()

    result = payload_to_dict(payload)

    assert result == {"name": "demo"}
    assert payload.calls == [{"exclude_unset": True}]


def test_payload_to_dict_copies_mapping():
    source = {"name": "demo"}

    result = payload_to_dict(source)

    assert result == source
    assert result is not source


def test_payload_to_dict_handles_none():
    assert payload_to_dict(None) == {}
