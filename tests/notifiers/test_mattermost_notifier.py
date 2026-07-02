def test_mattermost_bot_payload_does_not_duplicate_plain_text_when_message_empty():
    from app.notifiers.mattermost.notifier import MattermostNotifier

    notifier = MattermostNotifier()

    class Dummy:
        pass

    channel = Dummy()
    channel.id = 1
    channel.config = {"channel_id": "mattermost-channel"}

    alert = Dummy()
    alert.id = 18187
    alert.title = "[P1] Storage ID: 34027"
    alert.message = ""
    alert.status = "firing"
    alert.severity = "critical"
    alert.source = "sentry"
    alert.assignee = None
    alert.team = None
    alert.service = None

    plain_text = (
        "NOTIFICATION: [P1] Storage ID: 34027\n"
        "Team: Cloud dev\n"
        "Service: storage-api\n"
        "Status: firing\n"
        "Severity: critical\n"
        "Priority: P1 Critical\n"
        "Assignee: unknown\n"
        "Source: sentry"
    )

    payload = notifier._build_post_payload(
        channel,
        alert,
        plain_text,
        "notification",
        include_actions=False,
    )

    attachment = payload["props"]["attachments"][0]

    assert attachment["text"] == ""
    assert "Team: Cloud dev" not in attachment["text"]
    assert attachment["fields"]
