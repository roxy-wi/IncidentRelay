---
title: Voice Provider Examples
description: Example custom voice providers for IncidentRelay.
---

# IncidentRelay Voice Provider Examples

This directory contains example custom voice providers.

## Files

```text
example_http.py        Full HTTP provider example with TTS, callbacks, DTMF and polling.
mango_template.py      Mango-like provider template. Adjust API details according to provider docs.
stub_callback_test.py  Minimal provider useful for callback tests.
```

## Install an example provider

```bash
sudo mkdir -p /usr/local/lib/incidentrelay/voice_providers
sudo cp examples/voice_providers/example_http.py \
  /usr/local/lib/incidentrelay/voice_providers/example_http.py
sudo systemctl restart incidentrelay
```

Then use this channel config:

```json
{
  "provider": "example_http",
  "call_on_severities": ["critical"],
  "test_phone": "+77001234567",
  "callback_secret": "change-me-channel-secret",
  "provider_config": {
    "api_url": "https://voice.example.com/api",
    "api_token": "${VOICE_API_TOKEN}",
    "timeout": 10
  }
}
```
