---
title: Slack Channel
description: Slack incoming webhook and Bot API notification setup.
---

# Slack channel

Slack is an outgoing notification channel.

IncidentRelay supports two Slack delivery modes:

1. Incoming webhook mode for one-way notifications.
2. Bot API mode with interactive `Acknowledge` and `Resolve` buttons and message updates.

Bot API interactive actions can be received in two ways:

- HTTP Request URL with a signing secret;
- Socket Mode through an outbound WebSocket connection with an app-level token.

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

HTTP actions configuration:

```json
{
  "mode": "bot_api",
  "connection_mode": "http",
  "bot_token": "xoxb-...",
  "channel_id": "C0123456789",
  "signing_secret": "..."
}
```

Socket Mode configuration:

```json
{
  "mode": "bot_api",
  "connection_mode": "socket_mode",
  "bot_token": "xoxb-...",
  "app_token": "xapp-...",
  "channel_id": "C0123456789"
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

## Choose the interactive action transport

### HTTP Request URL

Use HTTP mode when Slack can reach IncidentRelay over public HTTPS.


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

## Socket Mode

Socket Mode is recommended for private networks, NAT and firewall-restricted installations. IncidentRelay opens an outbound WebSocket connection to Slack, so no public Request URL or `public_base_url` is required for the action buttons.

In the Slack app settings:

1. Open **Settings → Socket Mode** and enable Socket Mode.
2. Open **Basic Information → App-Level Tokens**.
3. Generate a token with the `connections:write` scope.
4. Copy the token beginning with `xapp-`.
5. Keep **Interactivity & Shortcuts** enabled; no Request URL is needed in Socket Mode.

In IncidentRelay select **Bot API → Socket Mode** and enter the bot token, app-level token and Slack channel ID.

The Slack worker must be running. Docker Compose includes `incidentrelay-slack`. For systemd:

```bash
sudo cp etc/systemd/incidentrelay-slack-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now incidentrelay-slack-worker
```

Check status:

```bash
systemctl status incidentrelay-slack-worker
journalctl -u incidentrelay-slack-worker -f
```

One Socket Mode connection is opened for each distinct app-level token. Multiple IncidentRelay Slack channels may share the same Slack app and app-level token.

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
4. Enter the Bot token and Channel ID.
5. Select the interactive action connection:
   - **HTTP Request URL** and enter the Signing Secret; or
   - **Socket Mode** and enter the App-Level Token.
6. Save the channel.
7. Attach the channel to the required route.
8. Send a test notification or a real test alert.

For HTTP interactive actions, configure `public_base_url` and ensure Slack can reach `POST /api/integrations/slack/actions` over HTTPS. Socket Mode does not require this endpoint to be publicly reachable.

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

### Socket Mode worker has no connections

Check that:

- the Slack channel is enabled;
- `connection_mode` is `socket_mode`;
- the app token starts with `xapp-`;
- the app token has `connections:write`;
- Socket Mode is enabled in the Slack app;
- the Slack worker service or container is running;
- outbound HTTPS and WebSocket connections to Slack are allowed.
