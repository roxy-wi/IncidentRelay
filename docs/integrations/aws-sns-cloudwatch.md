# AWS SNS and CloudWatch integration

IncidentRelay can receive signed Amazon SNS messages and CloudWatch alarm notifications through a dedicated inbound integration. Messages are accepted only after the SNS signature, signing certificate URL, route source, route state, and exact Topic ARN have been validated.

## Endpoint

```text
POST /api/integrations/aws-sns/{route_id}
```

Example:

```text
https://incidentrelay.example.com/api/integrations/aws-sns/17
```

This endpoint does not use a route intake bearer token. Amazon SNS authenticates requests with its message signature, while IncidentRelay also requires the `TopicArn` to exactly match the value stored in the route.

## Create an IncidentRelay route

1. Open **Routes**.
2. Create a route.
3. Select **AWS SNS / CloudWatch** as the source.
4. Select the owning team.
5. Enter the exact SNS Topic ARN.
6. Configure matchers and grouping.
7. Select a rotation or escalation policy.
8. Enable and save the route.
9. Open route details and copy the SNS webhook URL.

Example Topic ARN:

```text
arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts
```

Recommended grouping:

```json
[
  "cloudwatch_alarm_arn"
]
```

This keeps all state changes for one CloudWatch alarm in the same IncidentRelay group.

## Create the SNS subscription

In Amazon SNS:

1. Open the topic whose ARN is configured in the route.
2. Create a subscription.
3. Select **HTTPS** as the protocol.
4. Set the endpoint to the IncidentRelay webhook URL.
5. Create the subscription.

Amazon SNS sends a signed `SubscriptionConfirmation` message. IncidentRelay validates it and confirms the subscription automatically.

## Configure a CloudWatch alarm

Attach the SNS topic to the CloudWatch alarm notification actions. For a complete lifecycle, send notifications for at least:

```text
ALARM
OK
```

`ALARM` creates or updates a firing IncidentRelay alert. `OK` resolves the existing alert because both notifications use the same CloudWatch alarm ARN.

`INSUFFICIENT_DATA` is treated as firing with warning severity.


## AWS CLI configuration example

The same setup can be created from the AWS CLI. First subscribe the IncidentRelay route endpoint to the SNS topic:

```bash
TOPIC_ARN='arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts'

aws sns subscribe \
  --topic-arn "$TOPIC_ARN" \
  --protocol https \
  --notification-endpoint 'https://incidentrelay.example.com/api/integrations/aws-sns/17'
```

IncidentRelay validates the signed `SubscriptionConfirmation` request and confirms the subscription automatically.

Then create or update a CloudWatch alarm and send both alarm and recovery actions to the same SNS topic:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name HighCPU \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 90 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$TOPIC_ARN" \
  --ok-actions "$TOPIC_ARN"
```

Using the same topic in both `--alarm-actions` and `--ok-actions` is what gives IncidentRelay the complete firing → resolved lifecycle.

## CloudWatch state mapping

| CloudWatch state | IncidentRelay status | Default severity |
|---|---|---|
| `ALARM` | `firing` | `critical` |
| `INSUFFICIENT_DATA` | `firing` | `warning` |
| `OK` | `resolved` | `info` |

A `severity` SNS message attribute overrides the default severity.

## Deduplication

IncidentRelay uses `AlarmArn` as both the external identifier and deduplication key.

Example:

```text
arn:aws:cloudwatch:eu-west-1:123456789012:alarm:HighCPU
```

The same ARN must be present in `ALARM` and `OK` notifications so that the existing alert is updated instead of duplicated.

## Normalized labels

Common labels include:

| IncidentRelay label | Source |
|---|---|
| `alertname` | `AlarmName` |
| `severity` | SNS attribute or state mapping |
| `aws_service` | `cloudwatch` |
| `aws_account_id` | `AWSAccountId` |
| `aws_region` | `Region` |
| `cloudwatch_alarm_arn` | `AlarmArn` |
| `cloudwatch_state` | `NewStateValue` |
| `cloudwatch_previous_state` | `OldStateValue` |
| `cloudwatch_metric_name` | `Trigger.MetricName` |
| `cloudwatch_namespace` | `Trigger.Namespace` |
| `cloudwatch_statistic` | `Trigger.Statistic` |
| `cloudwatch_unit` | `Trigger.Unit` |
| `cloudwatch_period` | `Trigger.Period` |
| `cloudwatch_evaluation_periods` | `Trigger.EvaluationPeriods` |
| `cloudwatch_datapoints_to_alarm` | `Trigger.DatapointsToAlarm` |
| `cloudwatch_comparison_operator` | `Trigger.ComparisonOperator` |
| `cloudwatch_threshold` | `Trigger.Threshold` |
| `cloudwatch_treat_missing_data` | `Trigger.TreatMissingData` |
| `sns_topic_arn` | SNS `TopicArn` |
| `sns_message_id` | SNS `MessageId` |

CloudWatch dimensions use the `dimension_` prefix. For example:

```text
dimension_instanceid=i-0123456789abcdef0
```

## SNS message attributes

String SNS message attributes are converted into labels.

```json
{
  "team": {
    "Type": "String",
    "Value": "sre"
  },
  "environment": {
    "Type": "String",
    "Value": "production"
  },
  "severity": {
    "Type": "String",
    "Value": "critical"
  }
}
```

These become:

```text
team=sre
environment=production
severity=critical
```

The `team` and `oncall_team` attributes can provide a team hint, but route matching remains authoritative.

## Example route matchers

Production only:

```json
{
  "environment": "production"
}
```

One AWS account:

```json
{
  "aws_account_id": "123456789012"
}
```

EC2 CPU alarms:

```json
{
  "cloudwatch_namespace": "AWS/EC2",
  "cloudwatch_metric_name": "CPUUtilization"
}
```

One EC2 instance:

```json
{
  "dimension_instanceid": "i-0123456789abcdef0"
}
```

All configured matchers must match.

## Example SNS notification

The `Message` field contains a JSON-encoded CloudWatch alarm payload.

```json
{
  "Type": "Notification",
  "MessageId": "sns-message-1",
  "TopicArn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts",
  "Subject": "ALARM: HighCPU",
  "Message": "{\"AlarmName\":\"HighCPU\",\"AWSAccountId\":\"123456789012\",\"NewStateValue\":\"ALARM\",\"NewStateReason\":\"Threshold crossed\",\"Region\":\"EU (Ireland)\",\"AlarmArn\":\"arn:aws:cloudwatch:eu-west-1:123456789012:alarm:HighCPU\",\"OldStateValue\":\"OK\"}",
  "Timestamp": "2026-06-21T10:00:01.000Z",
  "SignatureVersion": "2",
  "Signature": "base64-signature",
  "SigningCertURL": "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-example.pem"
}
```

A manually created payload with a placeholder signature is rejected. The signature must be generated by Amazon SNS.

## Composite alarms

Composite alarm payloads can contain:

- `AlarmRule`;
- `TriggeringChildren`.

IncidentRelay stores these values in annotations and preserves the full CloudWatch payload. Deduplication still uses the alarm ARN.

## Generic SNS notifications

When `Message` is not recognized as a CloudWatch alarm, IncidentRelay creates a generic SNS alert using:

- `Subject` as the title;
- `Message` as the message;
- `MessageId` as the external identifier and deduplication key;
- string message attributes as labels;
- `warning` as the default severity;
- `firing` as the status.

## Stored payload

IncidentRelay stores:

```text
payload.sns
payload.cloudwatch
```

The SNS signature is removed before the payload is stored. The rest of the SNS envelope and CloudWatch alarm body remain available for diagnostics and auditing.

## Signature validation

Before accepting a request, IncidentRelay checks:

1. the route exists;
2. the route source is `aws_sns`;
3. the route, team, and group are active;
4. the SNS envelope is valid;
5. optional SNS headers match the JSON body;
6. `TopicArn` exactly matches the route configuration;
7. `SigningCertURL` uses HTTPS;
8. the certificate host and path belong to Amazon SNS;
9. the certificate is currently valid;
10. the RSA signature matches the canonical SNS signing string.

Signature algorithms:

| Signature version | Digest |
|---|---|
| `1` | SHA-1 |
| `2` | SHA-256 |

## Subscription responses

Successful confirmation:

```json
{
  "status": "confirmed",
  "message_id": "sns-confirmation-1",
  "topic_arn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts"
}
```

Unsubscribe confirmation:

```json
{
  "status": "unsubscribed",
  "message_id": "sns-confirmation-2",
  "topic_arn": "arn:aws:sns:eu-west-1:123456789012:incidentrelay-alerts"
}
```

## Successful notification response

```json
[
  {
    "created": true,
    "alert_id": 123,
    "group_id": 45,
    "status": "firing",
    "team_id": 2,
    "team_slug": "sre",
    "route_id": 17,
    "routing_error": null,
    "trace_id": "..."
  }
]
```

## HTTP responses

| Status | Meaning |
|---|---|
| `200` | Notification processed or subscription state confirmed |
| `202` | Processing accepted but not fully completed synchronously |
| `207` | Mixed ingest outcomes |
| `400` | Invalid envelope, headers, route source, or confirmation data |
| `403` | Signature, Topic ARN, route, team, or group validation failed |
| `404` | Route not found |
| `502` | Signing certificate download or subscription confirmation failed |

## Troubleshooting

### Subscription remains pending

Check that:

- the IncidentRelay endpoint is publicly reachable through HTTPS;
- the route source is `aws_sns`;
- the route is active;
- the configured Topic ARN exactly matches the SNS topic;
- IncidentRelay can reach Amazon SNS certificate and confirmation URLs;
- the reverse proxy forwards POST bodies unchanged.

### Topic ARN mismatch

Check the AWS partition, region, account ID, topic name, and optional `.fifo` suffix. The comparison is exact.

### Signature verification failed

Do not edit or manually replay a signed SNS body. Any change to a signed field invalidates the signature.

Also verify:

- outbound HTTPS access from IncidentRelay;
- system clock synchronization;
- that the body is not rewritten by a proxy;
- that the message came from the configured topic.

### Alarm does not resolve

Make sure CloudWatch sends a notification when the alarm enters `OK`. The `ALARM` and `OK` messages must contain the same `AlarmArn`.

### Alert did not match a route

Use the returned `trace_id` to inspect routing. Verify route state, team state, assignment target, and every configured matcher.

### Multiple alarms are grouped together

Use:

```json
[
  "cloudwatch_alarm_arn"
]
```

as the route grouping configuration.

## Security recommendations

- Use HTTPS only.
- Use a dedicated SNS topic per environment or trust boundary.
- Configure the exact Topic ARN on each route.
- Do not disable certificate URL validation.
- Do not accept redirects when loading certificates or confirming subscriptions.
- Keep IncidentRelay system time synchronized.
- Review routing traces and logs after rejected requests.
