# IncidentRelay Custom Voice Providers

This directory is used for custom IncidentRelay voice call providers.

A voice provider is a Python module that knows how to place a phone call through a specific provider API: Mango, Voximplant, Zadarma, Asterisk gateway, internal PBX, or any other service.

IncidentRelay itself does not need to know provider-specific API details. It loads your provider module and communicates with it through a stable provider API.

The current provider API supports:

```text
- Text-to-speech call creation
- Provider call ID tracking
- Call status callbacks
- DTMF button callbacks
- ACK / Resolve actions from phone keypad
- Optional call status polling
```

---

## Directory

Default custom providers directory:

```text
/usr/local/lib/incidentrelay/voice_providers
```

Example:

```text
/usr/local/lib/incidentrelay/voice_providers/
├── README.md
├── mango.py
├── zadarma.py
└── internal_pbx.py
```

Only server administrators should be able to write to this directory, because provider files are executable Python code.

Recommended permissions:

```bash
sudo mkdir -p /usr/local/lib/incidentrelay/voice_providers
sudo chown root:root /usr/local/lib/incidentrelay/voice_providers
sudo chmod 755 /usr/local/lib/incidentrelay/voice_providers
```

---

## Main IncidentRelay configuration

IncidentRelay reads voice provider settings from the main config file.

Example:

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers

# Global fallback secret for voice provider callbacks.
# A channel-level callback_secret has higher priority.
callback_secret =
```

### provider

Default provider name.

A notification channel may override this value in its own config:

```json
{
  "provider": "mango"
}
```

### providers_dir

Directory where custom provider modules are stored.

### callback_secret

Global fallback secret for voice callbacks.

Provider callback URLs use this format:

```text
/api/integrations/voice/rule-callback/{delivery_id}
```

If the channel config contains `callback_secret`, IncidentRelay uses the channel secret instead of the global one.

---

## Provider file name

Provider file names must contain only letters, numbers and underscore.

Valid examples:

```text
mango.py
zadarma.py
internal_pbx.py
voice_gateway_1.py
```

Invalid examples:

```text
mango-provider.py
my.provider.py
provider backup.py
```

The provider name used in channel config is the file name without `.py`.

Example file:

```text
/usr/local/lib/incidentrelay/voice_providers/mango.py
```

Provider name:

```json
"provider": "mango"
```

---

## Minimal provider

Every provider module must define a class named `Provider`.

The class must inherit from:

```python
app.notifiers.voice.base.BaseVoiceProvider
```

Minimal example:

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

---

## Provider API overview

A provider may implement the following methods:

```python
place_call()
parse_callback()
get_call_status()
validate_config()
```

Only `place_call()` is required.

Callback and polling methods are optional and depend on what your provider supports.

---

## Provider capabilities

Each provider should declare its capabilities.

Example:

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

Example statuses:

```text
queued
ringing
answered
completed
failed
busy
no_answer
cancelled
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

---

## VoiceCallRequest

`place_call()` receives one `VoiceCallRequest`.

Example:

```python
def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
    ...
```

### Fields

```python
request.phone
```

Target phone number.

```python
request.text
```

Text that should be spoken during the call.

```python
request.alert_id
```

IncidentRelay alert ID.

```python
request.event_type
```

Notification event type.

Possible values:

```text
notification
reminder
escalation
test
```

```python
request.callback_url
```

Callback URL that the provider should call when call status changes or DTMF digits are received.

Example:

```text
https://incidentrelay.example.com/api/integrations/voice/rule-callback/1234
```

May be `None` if callbacks are not configured.

```python
request.callback_secret
```

Callback secret used in the callback URL.

Most providers do not need to use it directly if `callback_url` is passed as-is.

```python
request.severity
```

Alert severity.

Example:

```text
critical
high
warning
info
```

```python
request.title
```

Alert title.

```python
request.message
```

Alert message.

```python
request.assignee
```

Human-readable assignee name.

```python
request.team
```

Team slug.

```python
request.action_hints
```

Recommended keypad actions.

Example:

```python
{
    "1": "acknowledge",
    "2": "resolve"
}
```

The provider may use this data to configure IVR / DTMF handling.

```python
request.metadata
```

Additional IncidentRelay metadata.

Example:

```python
{
    "channel_id": 1,
    "channel_name": "infra-voice-critical",
    "channel_type": "voice_call"
}
```

---

## VoiceCallResult

`place_call()` and `get_call_status()` must return `VoiceCallResult`.

Example:

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

---

## VoiceCallCallbackEvent

`parse_callback()` must return a list of `VoiceCallCallbackEvent` objects.

Example:

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

```python
call_id
```

External provider call ID.

Must match the `call_id` previously returned by `place_call()`.

```python
event_type
```

Normalized callback event type.

Recommended values:

```text
status
dtmf
error
```

```python
status
```

Call status.

Example:

```text
answered
completed
failed
busy
no_answer
```

```python
digit
```

DTMF digit pressed by the call recipient.

Example:

```text
1
2
```

```python
action
```

Optional normalized IncidentRelay action.

Supported actions:

```text
acknowledge
resolve
```

If `action` is not set, IncidentRelay maps `digit` through channel config `dtmf_actions`.

```python
alert_id
```

Optional alert ID.

Usually not required because IncidentRelay resolves the alert through `call_id`.

```python
message
```

Optional human-readable callback message.

```python
raw
```

Original provider callback payload.

Do not include secrets.

---

## Channel configuration

Example voice channel config:

```json
{
  "provider": "example_http",
  "call_on_severities": ["critical", "high"],
  "test_phone": "+77001234567",
  "callback_secret": "change-me-channel-secret",
  "text_template": "IncidentRelay alert {alert_id}. {title}. Severity {severity}. {message}. Press 1 to acknowledge. Press 2 to resolve.",
  "dtmf_actions": {
    "1": "acknowledge",
    "2": "resolve"
  },
  "provider_config": {
    "api_url": "https://voice.example.com/api",
    "api_token": "${VOICE_API_TOKEN}",
    "from": "+77000000000",
    "timeout": 10
  }
}
```

---

## Channel config fields

### provider

Name of the provider module.

Example:

```json
"provider": "mango"
```

This loads:

```text
/usr/local/lib/incidentrelay/voice_providers/mango.py
```

### call_on_severities

List of severities that should trigger a phone call.

Example:

```json
"call_on_severities": ["critical", "high"]
```

If this list is empty, IncidentRelay will not call anyone for real alerts.

### phone

Optional fallback phone number.

For real alerts, IncidentRelay usually uses the assigned user's phone number.

Example:

```json
"phone": "+77001234567"
```

### test_phone

Phone number used for test calls.

Example:

```json
"test_phone": "+77001234567"
```

### callback_secret

Optional per-channel callback secret.

If omitted, IncidentRelay uses global config:

```ini
[voice]
callback_secret =
```

### text_template

Template for the spoken message.

Supported placeholders:

```text
{alert_id}
{event_type}
{title}
{message}
{severity}
{status}
{team}
{assignee}
{source}
```

Example:

```json
"text_template": "Alert {alert_id}. {title}. Severity {severity}. Press 1 to acknowledge. Press 2 to resolve."
```

### dtmf_actions

Maps phone keypad digits to IncidentRelay actions.

Example:

```json
"dtmf_actions": {
  "1": "acknowledge",
  "2": "resolve"
}
```

Supported actions:

```text
acknowledge
resolve
```

### provider_config

Provider-specific settings.

IncidentRelay passes this object to the provider constructor.

Example:

```json
"provider_config": {
  "api_url": "https://voice.example.com/api",
  "api_token": "${VOICE_API_TOKEN}",
  "from": "+77000000000",
  "timeout": 10
}
```

Secrets should be stored in environment variables and referenced as `${ENV_NAME}`.

Example:

```json
"api_token": "${VOICE_API_TOKEN}"
```

---

## Config validation

A provider may define `validate_config()`.

This method is called before the provider is used.

Example:

```python
class Provider(BaseVoiceProvider):
    name = "mango"

    @classmethod
    def validate_config(cls, config):
        """Validate required provider settings."""

        required_fields = ["api_url", "api_token"]

        missing = [
            field
            for field in required_fields
            if not config.get(field)
        ]

        if missing:
            raise RuntimeError(
                f"mango provider config requires: {', '.join(missing)}"
            )
```

Use this method to check required fields early.

Good validation errors are important because they are shown in logs and help users fix channel configuration faster.

---

## Full provider example

This example supports:

```text
- TTS
- status callbacks
- DTMF callbacks
- status polling
```

File:

```text
/usr/local/lib/incidentrelay/voice_providers/example_http.py
```

Code:

```python
import requests

from app.notifiers.voice.base import (
    BaseVoiceProvider,
    VoiceCallCallbackEvent,
    VoiceCallRequest,
    VoiceCallResult,
    VoiceProviderCapabilities,
)


class Provider(BaseVoiceProvider):
    """Example provider with TTS, status callbacks and DTMF callbacks."""

    name = "example_http"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=True,
        dtmf_callback=True,
        status_polling=True,
    )

    @classmethod
    def validate_config(cls, config):
        """Validate provider config."""

        required = ["api_url", "api_token"]

        missing = [
            item
            for item in required
            if not config.get(item)
        ]

        if missing:
            raise RuntimeError(
                f"example_http config requires: {', '.join(missing)}"
            )

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Create a call through provider API."""

        payload = {
            "to": request.phone,
            "text": request.text,
            "callback_url": request.callback_url,
            "metadata": {
                "alert_id": request.alert_id,
                "event_type": request.event_type,
                "severity": request.severity,
                "team": request.team,
                "assignee": request.assignee,
            },
            "dtmf": {
                "enabled": True,
                "actions": request.action_hints,
            },
        }

        response = requests.post(
            f"{self.config['api_url'].rstrip('/')}/calls",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config['api_token']}",
            },
            timeout=int(self.config.get("timeout", 10)),
        )
        response.raise_for_status()

        data = response.json() if response.content else {}

        return VoiceCallResult(
            call_id=str(data.get("call_id") or data.get("id") or ""),
            status=str(data.get("status") or "queued"),
            raw=data,
        )

    def parse_callback(
        self,
        payload,
        headers=None,
        raw_body=None,
        query_args=None,
    ):
        """Normalize provider callback.

        Example provider callback:
        {
          "call_id": "abc-123",
          "event": "dtmf",
          "status": "answered",
          "digit": "1"
        }
        """

        call_id = str(payload.get("call_id") or payload.get("id") or "")

        if not call_id:
            raise RuntimeError("callback call_id is missing")

        event_type = str(payload.get("event") or payload.get("event_type") or "status")

        return [
            VoiceCallCallbackEvent(
                call_id=call_id,
                event_type=event_type,
                status=payload.get("status"),
                digit=payload.get("digit"),
                action=payload.get("action"),
                alert_id=payload.get("alert_id"),
                message=payload.get("message"),
                raw=payload,
            )
        ]

    def get_call_status(self, call_id: str) -> VoiceCallResult:
        """Fetch call status from provider API."""

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

---

## Callback flow

When IncidentRelay creates a call, it passes `callback_url` to the provider.

Example callback URL:

```text
https://incidentrelay.example.com/api/integrations/voice/rule-callback/1234
```

The provider should send call events to this URL.

Example status callback:

```json
{
  "call_id": "abc-123",
  "event_type": "status",
  "status": "answered"
}
```

Example DTMF callback:

```json
{
  "call_id": "abc-123",
  "event_type": "dtmf",
  "status": "answered",
  "digit": "1"
}
```

IncidentRelay will:

```text
1. Validate callback secret.
2. Load the voice provider configured for the channel.
3. Pass raw callback payload to provider.parse_callback().
4. Find notification by provider call_id.
5. Store callback status and payload.
6. Write callback event history.
7. Apply DTMF action if configured.
```

---

## DTMF actions

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

---

## Status callbacks

Providers may send status callbacks when the call state changes.

Recommended normalized statuses:

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

Example:

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

IncidentRelay stores the latest status in the notification record and also stores callback history.

---

## Error callbacks

Providers may send error events.

Example:

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

---

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

---

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

---

## Error handling

If a provider cannot place a call, it should raise an exception.

Good:

```python
try:
    response = requests.post(...)
    response.raise_for_status()
except requests.RequestException as exc:
    raise RuntimeError(
        f"{self.name} voice provider request failed: {exc}"
    ) from exc
```

Bad:

```python
try:
    response = requests.post(...)
except Exception:
    return VoiceCallResult(status="queued")
```

Do not silently ignore provider errors.

IncidentRelay will log the error and mark the notification attempt as failed according to its notification flow.

---

## Timeouts

Always use network timeouts.

Good:

```python
requests.post(url, json=payload, timeout=10)
```

Bad:

```python
requests.post(url, json=payload)
```

A provider without timeout may block notification workers.

---

## Secrets

Do not hardcode secrets in provider files.

Bad:

```python
api_token = "secret-token"
```

Good:

```json
"provider_config": {
  "api_token": "${VOICE_API_TOKEN}"
}
```

Then configure the environment variable for the IncidentRelay service:

```bash
export VOICE_API_TOKEN="secret-token"
```

For systemd, use an environment file or service environment configuration.

Example:

```ini
Environment="VOICE_API_TOKEN=secret-token"
```

---

## Logging

Providers may log useful operational information, but must not log secrets or full phone numbers.

Good:

```python
import logging

logger = logging.getLogger("oncall.voice")


def mask_phone(phone):
    if not phone:
        return None

    value = str(phone)

    if len(value) <= 4:
        return "****"

    return f"***{value[-4:]}"


logger.info(
    "placing voice call",
    extra={
        "extra": {
            "provider": self.name,
            "phone": mask_phone(request.phone),
            "alert_id": request.alert_id,
            "event_type": request.event_type,
        }
    },
)
```

Bad:

```python
logger.info(f"calling {request.phone} with token {self.config['api_token']}")
```

---

## Dependencies

If your provider needs additional Python packages, install them into the same Python environment where IncidentRelay runs.

Example:

```bash
pip install requests
```

If IncidentRelay is installed in a virtual environment:

```bash
/path/to/venv/bin/pip install requests
```

For Docker installations, custom dependencies should be added to the image or mounted according to your deployment model.

---

## Reloading providers

After adding or changing a provider file, restart IncidentRelay.

Example for systemd:

```bash
sudo systemctl restart incidentrelay
```

Provider classes may be cached by the loader, so restarting the service is the safest way to apply provider code changes.

---

## Security notes

Custom providers are executable Python code.

Only install providers from trusted sources.

Recommended rules:

```text
- The providers directory must not be writable by the web server user.
- The providers directory must not be writable from the IncidentRelay UI.
- Provider files should be reviewed before installation.
- Secrets should be passed through environment variables.
- Provider logs must not contain API tokens, passwords or full phone numbers.
- Callback secrets should be unique and hard to guess.
- Provider-specific webhook signatures should be validated when supported.
```

Do not allow untrusted users to upload provider files.

---

## Testing checklist

Before enabling a provider in production:

```text
1. Create a test voice channel.
2. Set test_phone.
3. Configure only one test severity, for example critical.
4. Trigger a test notification.
5. Check IncidentRelay logs.
6. Check provider-side logs or dashboard.
7. Confirm that call_id is returned.
8. Confirm that call status callbacks are received.
9. Confirm that DTMF callback with digit 1 acknowledges the alert.
10. Confirm that DTMF callback with digit 2 resolves the alert.
11. Confirm that provider errors are visible in IncidentRelay logs.
12. Confirm that secrets and full phone numbers are not logged.
13. Enable the provider for real alert routes.
```

---

## Common problems

### Provider not found

Error example:

```text
voice provider not found: mango
```

Check:

```text
- File exists: /usr/local/lib/incidentrelay/voice_providers/mango.py
- Channel config has: "provider": "mango"
- File name contains only letters, numbers and underscore
- IncidentRelay was restarted after adding the file
```

### Provider class is missing

Error example:

```text
voice provider mango must define Provider(BaseVoiceProvider)
```

Check that your module contains:

```python
class Provider(BaseVoiceProvider):
    ...
```

The class name must be exactly:

```text
Provider
```

### Config field is missing

Error example:

```text
mango config requires: api_url, api_token
```

Check `provider_config` in channel config.

### API token is empty

If you use:

```json
"api_token": "${VOICE_API_TOKEN}"
```

Check that the environment variable exists for the IncidentRelay process.

For systemd:

```bash
sudo systemctl show incidentrelay --property=Environment
```

Or check your service unit / environment file.

### Calls are not sent for real alerts

Check:

```text
- Alert status is firing.
- Alert severity is listed in call_on_severities.
- Alert has an assignee with phone number, or channel config has fallback phone.
- Channel is enabled.
- Route points to the voice channel.
```

### Callback is rejected

Check:

```text
- Callback URL contains the correct channel_id.
- Callback URL contains the correct callback secret.
- Channel type is voice_call.
- Channel config has the expected provider.
- Provider sends JSON or form data supported by parse_callback().
```

### DTMF does not acknowledge or resolve the alert

Check:

```text
- Provider sends event_type=dtmf or equivalent data that parse_callback() maps to dtmf.
- Provider sends digit.
- Channel config dtmf_actions contains this digit.
- The digit maps to acknowledge or resolve.
- call_id matches the original VoiceCallResult.call_id.
```

### Notification not found for callback

Check:

```text
- Provider returned call_id from place_call().
- Provider sends the same call_id in callbacks.
- IncidentRelay stored external_message_id for the notification.
- Callback is sent to the same channel_id that created the call.
```

---

## Recommended provider template

Use this template for new providers:

```python
import logging
import requests

from app.notifiers.voice.base import (
    BaseVoiceProvider,
    VoiceCallCallbackEvent,
    VoiceCallRequest,
    VoiceCallResult,
    VoiceProviderCapabilities,
)

logger = logging.getLogger("oncall.voice")


class Provider(BaseVoiceProvider):
    """Custom IncidentRelay voice provider."""

    name = "my_provider"

    capabilities = VoiceProviderCapabilities(
        tts=True,
        status_callback=True,
        dtmf_callback=True,
        status_polling=False,
    )

    @classmethod
    def validate_config(cls, config):
        """Validate required provider settings."""

        required_fields = ["api_url", "api_token"]

        missing = [
            field
            for field in required_fields
            if not config.get(field)
        ]

        if missing:
            raise RuntimeError(
                f"{cls.name} config requires: {', '.join(missing)}"
            )

    def place_call(self, request: VoiceCallRequest) -> VoiceCallResult:
        """Place a voice call."""

        payload = {
            "to": request.phone,
            "text": request.text,
            "callback_url": request.callback_url,
            "metadata": {
                "alert_id": request.alert_id,
                "event_type": request.event_type,
                "severity": request.severity,
                "team": request.team,
                "assignee": request.assignee,
            },
            "dtmf": {
                "enabled": True,
                "actions": request.action_hints,
            },
        }

        try:
            response = requests.post(
                f"{self.config['api_url'].rstrip('/')}/calls",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config['api_token']}",
                },
                timeout=int(self.config.get("timeout", 10)),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"{self.name} voice provider request failed: {exc}"
            ) from exc

        data = response.json() if response.content else {}

        return VoiceCallResult(
            call_id=str(data.get("call_id") or data.get("id") or ""),
            status=str(data.get("status") or "queued"),
            raw=data,
        )

    def parse_callback(
        self,
        payload,
        headers=None,
        raw_body=None,
        query_args=None,
    ):
        """Normalize provider callback."""

        call_id = str(payload.get("call_id") or payload.get("id") or "")

        if not call_id:
            raise RuntimeError("callback call_id is missing")

        event_type = str(payload.get("event_type") or payload.get("event") or "status")

        return [
            VoiceCallCallbackEvent(
                call_id=call_id,
                event_type=event_type,
                status=payload.get("status"),
                digit=payload.get("digit"),
                action=payload.get("action"),
                alert_id=payload.get("alert_id"),
                message=payload.get("message"),
                raw=payload,
            )
        ]
```