---
title: Callbacks and DTMF
description: Voice provider callbacks, statuses and keypad actions
---

# Callbacks and DTMF

IncidentRelay can receive provider callbacks for:

- call status changes;
- DTMF phone keypad input;
- provider errors.

## Callback URL

When IncidentRelay creates a call, it passes `callback_url` to the provider.

Example:

```text
https://incidentrelay.example.com/api/integrations/voice/rule-callback/1234
```

Providers must use the `request.callback_url` supplied by IncidentRelay instead
of constructing callback URLs themselves. The callback credential is never part
of the URL. Send `request.callback_secret` in one of these headers:

```http
Authorization: Bearer <callback_secret>
```

or:

```http
X-IncidentRelay-Callback-Secret: <callback_secret>
```

## Callback flow

The provider should send call events to the callback URL.

IncidentRelay will:

```text
1. Validate the callback secret from the request header.
2. Load the globally configured voice provider.
3. Pass raw callback payload to provider.parse_callback().
4. Find notification by provider call_id.
5. Store callback status and payload.
6. Write callback event history.
7. Apply DTMF action if configured.
```

## Status callback

Example provider callback:

```json
{
  "call_id": "abc-123",
  "event_type": "status",
  "status": "answered"
}
```

Provider normalization:

```python
return [
    VoiceCallCallbackEvent(
        call_id=payload["call_id"],
        event_type="status",
        status=payload["status"],
        raw=payload,
    )
]
```

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

IncidentRelay stores the latest status in the notification record and also stores callback history.

## DTMF callback

DTMF means phone keypad input.

Default mapping:

```json
{
  "1": "acknowledge",
  "2": "resolve"
}
```

Example spoken message:

```text
IncidentRelay alert 123.
Disk is full.
Severity critical.
Press 1 to acknowledge.
Press 2 to resolve.
```

If the user presses `1`, provider sends:

```json
{
  "call_id": "abc-123",
  "event_type": "dtmf",
  "digit": "1"
}
```

IncidentRelay maps it to:

```text
acknowledge
```

If the user presses `2`, IncidentRelay maps it to:

```text
resolve
```

A provider may also send the normalized action directly:

```json
{
  "call_id": "abc-123",
  "event_type": "dtmf",
  "action": "acknowledge"
}
```

In this case IncidentRelay does not need to map the digit.

## Error callback

Providers may send error events.

```json
{
  "call_id": "abc-123",
  "event_type": "error",
  "status": "failed",
  "message": "Insufficient balance"
}
```

Provider normalization:

```python
return [
    VoiceCallCallbackEvent(
        call_id=payload["call_id"],
        event_type="error",
        status="failed",
        message=payload.get("message"),
        raw=payload,
    )
]
```

## Provider-specific callback signatures

Some providers sign webhook callbacks.

`parse_callback()` receives:

```python
payload
headers
raw_body
query_args
```

Use `headers` and `raw_body` to validate provider signatures.

Example:

```python
def parse_callback(self, payload, headers=None, raw_body=None, query_args=None):
    signature = headers.get("X-Provider-Signature") if headers else None

    if not self._is_valid_signature(raw_body or b"", signature):
        raise RuntimeError("invalid provider callback signature")

    ...
```

IncidentRelay validates its own callback secret before calling `parse_callback()`.

Provider-specific signature validation is optional but recommended when the provider supports it.

## Polling call status

Some providers do not support callbacks.

In this case, the provider may implement:

```python
def get_call_status(self, call_id: str) -> VoiceCallResult:
    ...
```

Example:

```python
def get_call_status(self, call_id: str) -> VoiceCallResult:
    response = requests.get(
        f"{self.config['api_url'].rstrip('/')}/calls/{call_id}",
        headers={
            "Authorization": f"Bearer {self.config['api_token']}",
        },
        timeout=int(self.config.get("timeout", 10)),
    )
    response.raise_for_status()

    data = response.json() if response.content else {}

    return VoiceCallResult(
        call_id=call_id,
        status=str(data.get("status") or "unknown"),
        raw=data,
    )
```

Set capability:

```python
capabilities = VoiceProviderCapabilities(
    tts=True,
    status_callback=False,
    dtmf_callback=False,
    status_polling=True,
)
```
