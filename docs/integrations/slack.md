---
title: Slack Channel
description: Slack incoming webhook and Bot API notification setup.
---

# Slack channel

Slack is an outgoing notification channel.

IncidentRelay supports two Slack delivery modes:

1. Incoming webhook mode for one-way notifications.
2. Bot API mode with interactive `Acknowledge` and `Resolve` buttons and message updates.

Bot API mode is recommended when responders should manage alerts directly from Slack.

## Incoming webhook mode

Use this mode when you only need to send notifications.

Create an incoming webhook in Slack and configure the channel with:

```json
{
  "mode": "webhook",
  "webhook_url": "https://hooks.slack.com/services/..."
}
```

Incoming webhook messages cannot be updated by IncidentRelay after an alert is acknowledged or resolved.

## Bot API mode

Bot API mode supports:

- sending alert notifications with Block Kit;
- `Acknowledge` and `Resolve` buttons;
- updating the original Slack message after ACK or resolve;
- removing actions after the alert is resolved;
- optional attribution to an IncidentRelay user.

Typical channel configuration:

```json
{
  "mode": "bot_api",
  "bot_token": "xoxb-...",
  "channel_id": "C0123456789",
  "signing_secret": "..."
}
```

## Create the Slack app

1. Open the Slack app management page.
2. Create a new app for the target workspace.
3. Open **OAuth & Permissions**.
4. Add the bot token scope:

   ```text
   chat:write
   ```

5. Install or reinstall the app in the workspace.
6. Copy the **Bot User OAuth Token**. It normally starts with `xoxb-`.
7. Invite the bot to the Slack channel that will receive IncidentRelay alerts.

IncidentRelay uses `chat.postMessage` to send messages and `chat.update` to update existing messages.

## Enable interactive actions

Open **Interactivity & Shortcuts** in the Slack app settings and enable interactivity.

Set the Request URL to:

```text
https://incidentrelay.example.com/api/integrations/slack/actions
```

Replace `https://incidentrelay.example.com` with the configured IncidentRelay public URL.

IncidentRelay validates every interaction using:

- `X-Slack-Signature`;
- `X-Slack-Request-Timestamp`;
- the Slack app signing secret.

Requests older than five minutes are rejected.

## Find the signing secret

Open **Basic Information** in the Slack app settings and find **App Credentials**.

Copy the **Signing Secret** into the IncidentRelay Slack channel configuration.

Do not use the old Slack verification token. IncidentRelay validates signed requests using the signing secret.

## Find the channel ID

Open the target Slack channel and copy its channel ID.

Use the ID, such as:

```text
C0123456789
```

Do not enter the channel display name.

The bot must be able to post to the configured channel.

## Configure IncidentRelay

In IncidentRelay:

1. Open **Channels**.
2. Create or edit a Slack channel.
3. Select **Bot API**.
4. Enter:
   - Bot token;
   - Channel ID;
   - Signing secret.
5. Save the channel.
6. Attach the channel to the required route.
7. Send a test notification or a real test alert.

For interactive actions, configure the public URL:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

The Slack workspace must be able to reach:

```text
POST /api/integrations/slack/actions
```

Use HTTPS in production.

## User attribution

An IncidentRelay user can have a Slack user ID in their profile.

When a responder clicks `Acknowledge` or `Resolve`, IncidentRelay reads the Slack user ID from the interaction payload and tries to match it to an active IncidentRelay user.

If no matching user exists, the action can still be processed, but it will not be attributed to a local user.

## Message behavior

For a firing alert, the Slack message contains:

- alert title and description;
- status, severity and priority;
- team, service and assignee;
- service links and runbooks when configured;
- a link to the alert in IncidentRelay;
- `Acknowledge` and `Resolve` buttons.

After acknowledgment:

- the original message is updated;
- the status changes to acknowledged;
- the `Acknowledge` button is removed;
- the `Resolve` button remains.

After resolution:

- the original message is updated;
- the status changes to resolved;
- all action buttons are removed.

Incoming webhook mode only sends messages and does not support these updates.

## Test button

The channel test verifies that IncidentRelay can send a message using the configured Slack credentials.

It does not prove that:

- the channel is attached to the correct route;
- route matchers accept a real alert;
- severity filters allow the alert;
- Slack can reach the interactive actions endpoint.

Use a real test alert to verify the complete workflow.

## Troubleshooting

### Slack returns `invalid_auth`

Check that:

- the token starts with `xoxb-`;
- the app is installed in the correct workspace;
- the token has not been revoked;
- the app was reinstalled after changing scopes.

### Slack returns `not_in_channel`

Invite the bot to the configured Slack channel.

### Messages are sent but buttons do not work

Check that:

- Bot API mode is selected;
- Interactivity is enabled in the Slack app;
- the Request URL is correct;
- `public_base_url` is correct;
- the IncidentRelay endpoint is publicly reachable over HTTPS;
- the signing secret matches the Slack app;
- reverse proxies preserve the request body and Slack signature headers.

### Slack action is rejected as stale

Slack interaction requests older than five minutes are rejected.

Check system time synchronization on the IncidentRelay server and reverse proxy.

### Slack action is rejected for a channel mismatch

The Slack channel ID in the interaction must match the Channel ID configured in IncidentRelay.

Check that the notification was sent to the expected Slack channel and that the IncidentRelay channel configuration has not been changed.

### Messages are not updated

Message updates require Bot API mode.

Check that the original delivery stored both:

- the Slack channel ID;
- the Slack message timestamp.

Incoming webhook deliveries cannot be updated.

## Security notes

- Keep the bot token and signing secret private.
- Do not include either value in logs, screenshots or support requests.
- Rotate the bot token and signing secret if they are exposed.
- Expose only the required IncidentRelay HTTPS endpoints.
- Keep server time synchronized so timestamp validation works correctly.

## Slack references

- [Verifying requests from Slack](https://api.slack.com/authentication/verifying-requests-from-slack)
- [Handling interactions](https://api.slack.com/interactivity/handling)
- [chat.postMessage](https://api.slack.com/methods/chat.postMessage)
- [chat.update](https://api.slack.com/methods/chat.update)
- [Incoming webhooks](https://api.slack.com/messaging/webhooks)
