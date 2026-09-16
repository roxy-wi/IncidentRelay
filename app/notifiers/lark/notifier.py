import base64
import hashlib
import hmac
import time

from app.notifiers.base import BaseNotifier
from app.services.outbound_http import safe_request


class LarkNotifier(BaseNotifier):
    """Send notifications through a Feishu or Lark custom bot."""

    name = "lark"

    def send(self, channel, alert, text, event_type="notification"):
        """Send a text message through a Feishu/Lark webhook."""
        config = channel.config or {}
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            raise RuntimeError("webhook_url is missing")

        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }

        signing_secret = config.get("signing_secret")
        if signing_secret:
            timestamp = str(int(time.time()))
            payload.update(
                {
                    "timestamp": timestamp,
                    "sign": self._generate_signature(
                        signing_secret,
                        timestamp,
                    ),
                }
            )

        response = safe_request(
            "POST",
            webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        self._validate_response(response)

        return {"provider": self.name}

    @staticmethod
    def _generate_signature(secret, timestamp):
        """Return the signature expected by signed custom bots."""
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _validate_response(response):
        """Raise when Feishu/Lark reports an application-level error."""
        try:
            result = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Feishu/Lark webhook returned invalid JSON"
            ) from exc

        if not isinstance(result, dict):
            raise RuntimeError(
                "Feishu/Lark webhook returned an invalid response"
            )

        if "code" in result:
            if result.get("code") == 0:
                return
            message = result.get("msg") or "unknown error"
            raise RuntimeError(
                f"Feishu/Lark webhook error: {message}"
            )

        if "StatusCode" in result:
            if result.get("StatusCode") == 0:
                return
            message = result.get("StatusMessage") or "unknown error"
            raise RuntimeError(
                f"Feishu/Lark webhook error: {message}"
            )

        raise RuntimeError(
            "Feishu/Lark webhook returned an invalid response"
        )
