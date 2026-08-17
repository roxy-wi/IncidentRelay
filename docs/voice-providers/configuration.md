---
title: Voice Provider Configuration
description: IncidentRelay voice provider configuration
---

# Voice Provider Configuration

## Main IncidentRelay configuration

IncidentRelay reads voice provider settings from the main config file.

Example:

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret =
text_template = IncidentRelay alert {alert_id}. {title}. Severity {severity}. {message}. Press 1 to acknowledge. Press 2 to resolve.
dtmf_actions = {"1": "acknowledge", "2": "resolve"}

[voice_provider]
api_url = https://voice.example.com/api
api_token = ${VOICE_API_TOKEN}
timeout = 10
```

## Settings

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

Recommended value:

```text
/usr/local/lib/incidentrelay/voice_providers
```

### callback_secret

Optional dedicated secret for voice callbacks. If empty, IncidentRelay falls back to the application secret. A dedicated random value is recommended.

The secret is passed to providers as `request.callback_secret` and must be sent back in the `Authorization: Bearer ...` header (or `X-IncidentRelay-Callback-Secret`). It must never be embedded in the callback URL. Providers should use `request.callback_url` exactly as supplied by IncidentRelay.

## Provider file names

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

## Channel config fields

### provider

Name of the provider module.

```json
"provider": "mango"
```

### call_on_severities

List of severities that should trigger a phone call.

```json
"call_on_severities": ["critical", "high"]
```

If this list is empty, IncidentRelay will not call anyone for real alerts.

### phone

Optional fallback phone number.

For real alerts, IncidentRelay usually uses the assigned user's phone number.

```json
"phone": "+77001234567"
```

### test_phone

Phone number used for test calls.

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

```json
"provider_config": {
  "api_url": "https://voice.example.com/api",
  "api_token": "${VOICE_API_TOKEN}",
  "from": "+77000000000",
  "timeout": 10
}
```

Secrets should be stored in environment variables and referenced as `${ENV_NAME}`.

```json
"api_token": "${VOICE_API_TOKEN}"
```

## Config validation

A provider may define `validate_config()`.

This method is called before the provider is used.

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
