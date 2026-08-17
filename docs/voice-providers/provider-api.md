---
title: Provider API
description: How to write a custom IncidentRelay voice provider
---

# Provider API

Every provider module must define a class named `Provider`.

The class must inherit from:

```python
app.notifiers.voice.base.BaseVoiceProvider
```

## Minimal provider

```python
from app.notifiers.voice.base import (
    BaseVoiceProvider,
    VoiceCallRequest,
    VoiceCallResult,
    VoiceProviderCapabilities,
)


class Provider(BaseVoiceProvider):
    """Minimal custom voice provider."""

    name = "example"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=False,
        dtmf_callback=False,
        status_polling=False,
    )

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Place a voice call."""

        print(f"Calling {request.phone}: {request.text}")

        return VoiceCallResult(
            call_id="example-call-id",
            status="queued",
            raw={"provider": self.name},
        )
```

## Provider methods

A provider may implement:

```python
place_call()
parse_callback()
get_call_status()
validate_config()
```

Only `place_call()` is required.

Callback and polling methods are optional and depend on what your provider supports.

## BaseVoiceProvider

```python
class BaseVoiceProvider:
    name = "base"

    capabilities = VoiceProviderCapabilities()

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> None:
        """Validate provider-specific configuration."""

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Place a voice call."""

        raise NotImplementedError

    def parse_callback(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        raw_body: bytes | None = None,
        query_args: dict[str, Any] | None = None,
    ) -> list[VoiceCallCallbackEvent]:
        """Parse provider webhook callback."""

        return []

    def get_call_status(self, call_id: str) -> VoiceCallResult:
        """Return current call status."""

        raise NotImplementedError
```

## Capabilities

Each provider should declare its capabilities.

```python
from app.notifiers.voice.base import VoiceProviderCapabilities


class Provider(BaseVoiceProvider):
    name = "mango"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=True,
        dtmf_callback=True,
        status_polling=False,
    )
```

### tts

Provider can receive text and play it during a call.

### status_callback

Provider can send webhook callbacks with call status changes.

Recommended statuses:

```text
queued
ringing
answered
completed
failed
busy
no_answer
cancelled
unknown
```

### dtmf_callback

Provider can send webhook callbacks when the user presses phone keypad buttons.

Example:

```text
1 -> acknowledge
2 -> resolve
```

### status_polling

Provider can return call status through an API request.

This is useful when the provider does not support callbacks.

## VoiceCallRequest

`place_call()` receives one `VoiceCallRequest`.

```python
def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
    ...
```

### Fields

| Field | Description |
|---|---|
| `request.phone` | Target phone number |
| `request.text` | Text that should be spoken during the call |
| `request.alert_id` | IncidentRelay alert ID |
| `request.event_type` | Notification event type: `notification`, `reminder`, `escalation`, `test` |
| `request.callback_url` | Callback URL for status and DTMF events |
| `request.callback_secret` | Server-only callback credential; send it in `Authorization: Bearer ...` (or `X-IncidentRelay-Callback-Secret`), never in the URL |
| `request.severity` | Alert severity |
| `request.title` | Alert title |
| `request.message` | Alert message |
| `request.assignee` | Human-readable assignee name |
| `request.team` | Team slug |
| `request.action_hints` | Recommended keypad actions |
| `request.metadata` | Additional IncidentRelay metadata |

Example `action_hints`:

```python
{
    "1": "acknowledge",
    "2": "resolve",
}
```

Example `metadata`:

```python
{
    "channel_id": 1,
    "channel_name": "infra-voice-critical",
    "channel_type": "voice_call",
}
```

## VoiceCallResult

`place_call()` and `get_call_status()` must return `VoiceCallResult`.

```python
return VoiceCallResult(
    call_id="abc-123",
    status="queued",
    raw=response_data,
)
```

### call_id

External call ID returned by the provider.

IncidentRelay stores it as `external_message_id`.

This ID is later used to match provider callbacks with the original alert notification.

### status

Normalized provider status.

Recommended values:

```text
queued
ringing
answered
completed
failed
busy
no_answer
cancelled
logged
unknown
```

### raw

Original provider response or useful debug information.

Do not put secrets into `raw`.

## VoiceCallCallbackEvent

`parse_callback()` must return a list of `VoiceCallCallbackEvent` objects.

```python
return [
    VoiceCallCallbackEvent(
        call_id="abc-123",
        event_type="dtmf",
        status="answered",
        digit="1",
        raw=payload,
    )
]
```

### Fields

| Field | Description |
|---|---|
| `call_id` | External provider call ID |
| `event_type` | Normalized event type: `status`, `dtmf`, `error` |
| `status` | Call status |
| `digit` | DTMF digit pressed by the call recipient |
| `action` | Optional normalized IncidentRelay action |
| `alert_id` | Optional alert ID |
| `message` | Optional human-readable callback message |
| `raw` | Original provider callback payload |

Supported actions:

```text
acknowledge
resolve
```
