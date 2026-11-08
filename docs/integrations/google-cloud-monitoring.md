# Google Cloud Monitoring

Send incidents directly from a Google Cloud Monitoring alerting policy to IncidentRelay. This integration accepts the [version 1.2 Webhook notification](https://docs.cloud.google.com/monitoring/support/notification-options#webhooks); it does not require Pub/Sub or a Cloud Function.

1. In **Routes**, create a route with source **Google Cloud Monitoring**, select the receiving team and save. Copy its intake token.
2. In Google Cloud Console, open **Monitoring → Alerting → Edit notification channels**. Add a **Webhook** channel using the public HTTPS URL `https://ir.example.com/api/integrations/google-cloud-monitoring`. Select **HTTP Basic**, enter `incidentrelay` for the username and the route intake token for the password. Keep the token out of the URL.
3. Attach the channel to your alerting policy and enable notifications on incident closure. Without closure notifications, IR only sees the opening event.

### Test the route

Save the following as `incident.json` and send it to a test route. The command prompts for the route token.

```json
{
  "version": "1.2",
  "incident": {
    "incident_id": "ir-test-001",
    "scoping_project_id": "example-project",
    "state": "open",
    "policy_name": "Checkout error rate",
    "severity": "Error",
    "resource": {"type": "cloud_run_revision"},
    "summary": "Checkout returned HTTP 500"
  }
}
```

```sh
curl --user incidentrelay -H 'Content-Type: application/json' \
  --data-binary @incident.json https://ir.example.com/api/integrations/google-cloud-monitoring
```

Send the same file twice: the second request updates the same alert. Change `state` to `closed` and send again to resolve it. A later `open` with the same project and incident ID on this route is ignored, even if `closed` arrived first. Use a fresh incident ID to repeat the test.

The project and Google incident ID are required. Use `gcp_project_id` and `gcp_incident_id` for grouping; `gcp_policy`, `gcp_condition`, `gcp_resource_type` and `gcp_resource_name` are available when supplied. The alert links back to the Google Cloud Console when the payload contains its URL. Severity maps as follows: Critical → critical, Error → high, Warning → warning; missing or unknown → info.

A processed alert returns **200**; **202** means no group was created (for example, a late notification was ignored). For **401**, check the username, current route token and route status. For **400**, check the route source, schema version, project, incident ID and state.
