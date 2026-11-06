"""Normalize Google Cloud Monitoring's version 1.2 incident notification."""

from app.api.schemas.integrations import GoogleCloudMonitoringWebhookSchema
from app.services.integrations.normalizers.common import make_dedup_key


def normalize_google_cloud_monitoring(payload, *, route_id=None):
    """Identify a Google incident independently of notification text and state."""
    envelope = GoogleCloudMonitoringWebhookSchema.model_validate(payload)
    incident = envelope.incident
    labels = {
        "gcp_incident_id": incident.incident_id,
        "gcp_project_id": incident.scoping_project_id,
    }
    optional_labels = {
        "gcp_policy": incident.policy_name,
        "gcp_condition": incident.condition_name,
        "gcp_resource_name": incident.resource_display_name or incident.resource_name,
        "gcp_resource_type": (incident.resource or {}).get("type"),
    }
    labels.update(
        {
            key: value
            for key, value in optional_labels.items()
            if isinstance(value, str) and value
        }
    )
    if incident.url and incident.url.startswith("https://console.cloud.google.com/"):
        labels["event_link"] = incident.url

    severity = (incident.severity or "").lower()
    return [
        {
            "source": "google_cloud_monitoring",
            "external_id": incident.incident_id,
            "dedup_key": make_dedup_key(
                "google_cloud_monitoring",
                external_id=[
                    route_id,
                    incident.scoping_project_id,
                    incident.incident_id,
                ],
            ),
            "title": (
                incident.policy_name or incident.condition_name or incident.incident_id
            )[:255],
            "message": incident.summary or "",
            "severity": {
                "critical": "critical",
                "error": "high",
                "warning": "warning",
            }.get(severity, "info"),
            "labels": labels,
            "payload": payload,
            "status": "resolved" if incident.state == "closed" else "firing",
        }
    ]
