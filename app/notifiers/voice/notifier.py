from app import Config
from app.modules.common import SafeFormatDict
from app.notifiers.base import BaseNotifier
from app.notifiers.plugins import logger
from app.notifiers.voice.base import VoiceCallRequest
from app.notifiers.voice.loader import create_voice_provider
from app.services.alerts.correlation import format_correlation_plain


class VoiceCallNotifier(BaseNotifier):
    """Send voice call notifications through a pluggable provider."""

    name = "voice_call"
    supports_update = False
    allowed_events = {"notification", "reminder", "escalation", "test"}

    def send(self, channel, alert, text, event_type="notification"):
        """Send a voice call through a configured provider."""
        config = channel.config or {}

        if event_type not in self.allowed_events:
            return self._skip("unsupported_event", channel, alert, event_type)

        if event_type != "test" and alert.status != "firing":
            return self._skip("alert_not_firing", channel, alert, event_type)

        phone = self._get_phone(alert)
        if not phone:
            raise RuntimeError("voice_call phone is missing: set phone on the assigned user")

        provider_name = Config.VOICE_PROVIDER
        provider_config = Config.VOICE_PROVIDER_CONFIG
        provider = create_voice_provider(provider_name, provider_config)
        call_text = self._build_call_text(alert, text, event_type)
        callback_secret = self._callback_secret()
        callback_url = config.get("callback_url")

        request = VoiceCallRequest(
            phone=phone,
            text=call_text,
            alert_id=getattr(alert, "id", None),
            event_type=event_type,
            callback_url=callback_url,
            callback_secret=callback_secret,
            severity=getattr(alert, "severity", None),
            title=getattr(alert, "title", None),
            message=getattr(alert, "message", None),
            assignee=self._assignee_name(alert),
            team=alert.team.slug if getattr(alert, "team", None) else None,
            action_hints=self._dtmf_actions(),
            metadata={
                "channel_id": getattr(channel, "id", None),
                "channel_name": getattr(channel, "name", None),
                "channel_type": getattr(channel, "channel_type", None),
            },
        )
        result = provider.place_call(request)

        return {
            "provider": f"{self.name}:{provider.name}",
            "external_message_id": result.call_id,
            "external_channel_id": str(channel.id),
            "provider_status": result.status,
            "provider_payload": result.raw,
        }

    def _get_phone(self, alert):
        """Return the assigned user's phone number."""
        assignee = getattr(alert, "assignee", None)
        if not assignee:
            return None
        return getattr(assignee, "phone", None)

    def _build_call_text(self, alert, fallback_text, event_type):
        """Build the text that the voice provider should say."""
        template = getattr(Config, "VOICE_TEXT_TEMPLATE", "") or (
            "IncidentRelay alert {alert_id}. "
            "{title}. "
            "Service {service}. "
            "Severity {severity}. "
            "{message}. "
            "Press 1 to acknowledge. "
            "Press 2 to resolve."
        )
        values = SafeFormatDict(
            alert_id=getattr(alert, "id", None) or "test",
            event_type=event_type,
            title=getattr(alert, "title", None) or "Alert",
            message=getattr(alert, "message", None) or fallback_text or "",
            severity=getattr(alert, "severity", None) or "-",
            status=getattr(alert, "status", None) or "-",
            team=alert.team.slug if getattr(alert, "team", None) else "-",
            assignee=self._assignee_name(alert) or "-",
            source=getattr(alert, "source", None) or "-",
            correlation=self._correlation_text(alert),
        )
        return template.format_map(values)

    def _assignee_name(self, alert):
        """Return a human-readable assignee name."""
        assignee = getattr(alert, "assignee", None)
        if not assignee:
            return None
        return getattr(assignee, "display_name", None) or getattr(
            assignee,
            "username",
            None,
        )

    def _callback_secret(self):
        """Return callback secret for voice provider callbacks."""
        return getattr(Config, "VOICE_CALLBACK_SECRET", "")

    def _callback_url(self, channel, callback_secret):
        """Return callback URL for this voice channel."""
        if not callback_secret:
            return None
        return (
            f"{Config.PUBLIC_BASE_URL.rstrip()}"
            f"/api/integrations/voice/callback/{channel.id}/{callback_secret}"
        )

    def _dtmf_actions(self):
        """Return globally configured digit-to-action mapping."""
        return getattr(
            Config,
            "VOICE_DTMF_ACTIONS",
            {"1": "acknowledge", "2": "resolve"},
        )

    def _skip(self, reason, channel, alert, event_type):
        """Return a skipped notification result."""
        logger.debug(
            "voice call skipped",
            extra={
                "extra": {
                    "reason": reason,
                    "channel_id": channel.id,
                    "channel_name": getattr(channel, "name", None),
                    "channel_type": getattr(channel, "channel_type", None),
                    "alert_id": getattr(alert, "id", None),
                    "event_type": event_type,
                    "severity": getattr(alert, "severity", None),
                    "status": getattr(alert, "status", None),
                }
            },
        )
        return {
            "provider": self.name,
            "skipped": True,
            "skip_reason": reason,
        }

    def _correlation_text(self, alert):
        """Return short voice-friendly correlation text."""
        lines = format_correlation_plain(alert)

        if not lines:
            return ""

        useful_lines = [
            line
            for line in lines
            if line.startswith("Role:")
               or line.startswith("Possible root cause:")
               or line.startswith("Possible downstream impact:")
               or line.startswith("- ")
        ]

        if not useful_lines:
            return ""

        return " ".join(useful_lines[:4])
