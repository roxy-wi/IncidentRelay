"""Slack mrkdwn escaping shared across the Slack notifier and the incident
participant message builders.

Slack treats ``&``, ``<`` and ``>`` as control characters: ``<!channel>`` and
``<!here>`` are broadcast commands and ``<@U...>`` is a user mention. Any
untrusted text (alert titles, display names, free-text responder/stakeholder
messages) must have these escaped before it is placed in a Slack message, so an
injected control sequence renders as literal text instead of pinging a channel
or a user. Deliberate, validated mentions are assembled separately from
already-escaped text and are never passed through this function.
"""


def escape_mrkdwn(value):
    """Escape Slack mrkdwn control characters in untrusted text."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
