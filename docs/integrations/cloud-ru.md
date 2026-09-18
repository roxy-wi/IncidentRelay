# Cloud.ru Advanced: Cloud Eye via SMN

IncidentRelay can receive Cloud.ru Advanced Cloud Eye alarms through Simple Message Notification (SMN).

## Architecture

```text
Cloud Eye -> SMN Topic -> signed HTTP/HTTPS subscription -> IncidentRelay Route
```

Cloud Eye can notify on both generated and cleared alarms. Configure both so IncidentRelay receives the complete `firing -> resolved` lifecycle.

## Configure IncidentRelay

1. Open **Routes**.
2. Create a route with source **Cloud.ru Cloud Eye / SMN**.
3. Select the owning team, notification settings, and optional default service.
4. Enter the exact **SMN Topic URN** used by Cloud Eye.
5. Save the route.
6. Copy the generated route-scoped webhook URL:

```text
https://incidentrelay.example/api/integrations/cloud-ru/<route_id>
```

SMN does not need an IncidentRelay bearer token. IncidentRelay authenticates the delivery by verifying the SMN V1 signature, the Cloud.ru signing certificate, and the exact Topic URN configured on the route.

## Configure Cloud.ru

1. Create an SMN topic in Cloud.ru Advanced.
2. Add an HTTP/HTTPS subscription whose endpoint is the IncidentRelay webhook URL.
3. IncidentRelay verifies and confirms the SMN subscription automatically.
4. In Cloud Eye, create or edit an alarm rule.
5. Enable **Alarm Notification** and select the SMN topic.
6. Enable both **Generated alarm** and **Cleared alarm** trigger conditions.

## Normalization

Cloud Eye alarm state is mapped as follows:

| Cloud Eye state | IncidentRelay status |
|---|---|
| `alarm` | `firing` |
| `ok`, `cleared`, `resolved` | `resolved` |
| other/unknown | `firing` |

Alarm levels are mapped as follows:

| Cloud.ru level | IncidentRelay severity |
|---|---|
| `1` / Critical | `critical` |
| `2` / Major | `high` |
| `3` / Minor | `warning` |
| `4` / Informational | `info` |

The Cloud Eye `alarm_id` is used as the stable deduplication key, so a cleared notification updates and resolves the existing alert instead of creating a second alert.

Matcher-friendly labels include `cloud_ru_alarm_id`, `cloud_ru_alarm_name`, `cloud_ru_alarm_status`, `cloud_ru_alarm_level`, `cloud_ru_namespace`, `cloud_ru_metric_name`, SMN topic/message identifiers, and dimension labels such as `cloud_ru_dimension_instance_id`.

## Security

IncidentRelay validates:

- route source and route/team state;
- exact SMN Topic URN;
- `X-SMN-MESSAGE-*` headers when present;
- SMN V1 RSA signature;
- signing certificate validity;
- HTTPS certificate URLs restricted to Cloud.ru DNS names;
- HTTPS subscription confirmation URLs restricted to Cloud.ru DNS names.

Redirects are disabled for signing-certificate and confirmation requests. This prevents signed SMN messages from being used as a generic SSRF primitive.

## Troubleshooting

`400 route_source_mismatch` means the route is not configured with source `cloud_ru`.

`403 cloud_ru_smn_topic_mismatch` means the incoming Topic URN differs from the route configuration.

`403 cloud_ru_smn_invalid_signature` means signature verification failed.

`403 cloud_ru_smn_invalid_certificate_url` means the signing certificate URL is not an allowed Cloud.ru HTTPS URL.

`502 cloud_ru_smn_certificate_unavailable` means IncidentRelay could not download the provider signing certificate.
