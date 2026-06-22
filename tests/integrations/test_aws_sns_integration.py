import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import (
    padding,
    rsa,
)
from cryptography.x509.oid import NameOID

from app.api.schemas.routes import RouteCreateSchema
from app.services.integrations.aws_sns import (
    AwsSnsError,
    build_aws_sns_signing_string,
    validate_aws_sns_message, validate_confirmation_url,
)
from app.services.integrations.normalizers.aws_sns import (
    normalize_aws_sns,
)
from tests.factories import (
    create_group,
    create_route,
    create_team,
)
from app.modules.db.models import (
    Alert,
    AlertExplainTrace,
    AlertGroup,
)


TOPIC_ARN = (
    "arn:aws:sns:eu-west-1:"
    "123456789012:incidentrelay-alerts"
)

CERT_URL = (
    "https://sns.eu-west-1.amazonaws.com/"
    "SimpleNotificationService-test.pem"
)


def create_aws_sns_route(
    *,
    group_slug="platform",
    team_slug="sre",
    group_by=None,
):
    group = create_group(slug=group_slug)
    team = create_team(group, slug=team_slug)

    route = create_route(
        team,
        source="aws_sns",
        group_by=group_by or [
            "cloudwatch_alarm_arn",
        ],
    )

    route.integration_config = {
        "aws_sns": {
            "topic_arn": TOPIC_ARN,
        },
    }
    route.save()

    return route, team


def cloudwatch_message(state="ALARM"):
    return {
        "AlarmName": "HighCPU",
        "AlarmDescription": "CPU usage is too high",
        "AWSAccountId": "123456789012",
        "NewStateValue": state,
        "NewStateReason": (
            "Threshold crossed: 1 datapoint was greater "
            "than the threshold."
        ),
        "StateChangeTime": "2026-06-21T10:00:00.000+0000",
        "Region": "EU (Ireland)",
        "AlarmArn": (
            "arn:aws:cloudwatch:eu-west-1:"
            "123456789012:alarm:HighCPU"
        ),
        "OldStateValue": (
            "OK" if state == "ALARM" else "ALARM"
        ),
        "Trigger": {
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/EC2",
            "StatisticType": "Statistic",
            "Statistic": "AVERAGE",
            "Unit": None,
            "Dimensions": [
                {
                    "name": "InstanceId",
                    "value": "i-0123456789abcdef0",
                },
            ],
            "Period": 300,
            "EvaluationPeriods": 1,
            "DatapointsToAlarm": 1,
            "ComparisonOperator": (
                "GreaterThanThreshold"
            ),
            "Threshold": 90,
            "TreatMissingData": "missing",
        },
    }


def sns_notification(state="ALARM"):
    return {
        "Type": "Notification",
        "MessageId": "sns-message-1",
        "TopicArn": TOPIC_ARN,
        "Subject": "ALARM: HighCPU",
        "Message": json.dumps(
            cloudwatch_message(state)
        ),
        "Timestamp": "2026-06-21T10:00:01.000Z",
        "SignatureVersion": "2",
        "Signature": "placeholder",
        "SigningCertURL": CERT_URL,
        "MessageAttributes": {
            "team": {
                "Type": "String",
                "Value": "sre",
            },
            "environment": {
                "Type": "String",
                "Value": "production",
            },
        },
    }


def test_normalize_cloudwatch_alarm():
    alert = normalize_aws_sns(
        sns_notification()
    )[0]

    assert alert["source"] == "aws_sns"
    assert alert["team_slug"] == "sre"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"

    assert alert["title"] == "HighCPU"
    assert alert["external_id"].endswith(
        ":alarm:HighCPU"
    )
    assert alert["dedup_key"].endswith(
        ":alarm:HighCPU"
    )

    assert alert["labels"]["aws_service"] == (
        "cloudwatch"
    )
    assert alert["labels"]["environment"] == (
        "production"
    )
    assert alert["labels"]["cloudwatch_metric_name"] == (
        "CPUUtilization"
    )
    assert alert["labels"]["cloudwatch_namespace"] == (
        "AWS/EC2"
    )
    assert alert["labels"]["dimension_instanceid"] == (
        "i-0123456789abcdef0"
    )


def test_normalize_cloudwatch_ok_as_resolved():
    alert = normalize_aws_sns(
        sns_notification("OK")
    )[0]

    assert alert["status"] == "resolved"
    assert alert["severity"] == "info"


def test_route_schema_requires_aws_sns_topic_arn():
    with pytest.raises(
        ValueError,
        match="Topic ARN",
    ):
        RouteCreateSchema(
            team_id=1,
            name="AWS SNS route",
            source="aws_sns",
            integration_config={},
        )


def test_route_schema_accepts_aws_sns():
    route = RouteCreateSchema(
        team_id=1,
        name="AWS SNS route",
        source="aws_sns",
        integration_config={
            "aws_sns": {
                "topic_arn": TOPIC_ARN,
            },
        },
    )

    assert route.source == "aws_sns"


def _certificate_and_key():
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME,
            "sns.eu-west-1.amazonaws.com",
        ),
    ])

    now = datetime.now(timezone.utc)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(
            x509.random_serial_number()
        )
        .not_valid_before(
            now - timedelta(minutes=1)
        )
        .not_valid_after(
            now + timedelta(days=1)
        )
        .sign(key, hashes.SHA256())
    )

    return certificate, key


def test_validate_aws_sns_signature(
    monkeypatch,
):
    envelope = sns_notification()
    certificate, key = _certificate_and_key()

    envelope["Signature"] = base64.b64encode(
        key.sign(
            build_aws_sns_signing_string(
                envelope
            ).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    ).decode("ascii")

    monkeypatch.setattr(
        "app.services.integrations.aws_sns."
        "_load_signing_certificate",
        lambda url: certificate,
    )

    assert validate_aws_sns_message(
        envelope,
        TOPIC_ARN,
    ) is True


def test_validate_aws_sns_rejects_tampering(
    monkeypatch,
):
    envelope = sns_notification()
    certificate, key = _certificate_and_key()

    envelope["Signature"] = base64.b64encode(
        key.sign(
            build_aws_sns_signing_string(
                envelope
            ).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    ).decode("ascii")

    envelope["Message"] = json.dumps({
        "AlarmName": "TamperedAlarm",
        "NewStateValue": "ALARM",
    })

    monkeypatch.setattr(
        "app.services.integrations.aws_sns."
        "_load_signing_certificate",
        lambda url: certificate,
    )

    with pytest.raises(
        AwsSnsError,
        match="verification failed",
    ):
        validate_aws_sns_message(
            envelope,
            TOPIC_ARN,
        )


def test_aws_sns_endpoint_processes_notification(
    client,
    monkeypatch,
    db,
):
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="aws_sns",
    )
    route.integration_config = {
        "aws_sns": {
            "topic_arn": TOPIC_ARN,
        },
    }
    route.save()

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        lambda envelope, expected_topic_arn: True,
    )

    calls = []

    def fake_process(alerts):
        calls.append(alerts)

        return {
            "ok": True,
            "count": len(alerts),
        }, 200

    monkeypatch.setattr(
        "app.views.integrations_view."
        "process_incoming_alerts",
        fake_process,
    )

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=sns_notification(),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "count": 1,
    }

    assert calls[0][0]["source"] == "aws_sns"
    assert calls[0][0]["title"] == "HighCPU"


def test_aws_sns_endpoint_rejects_wrong_source(
    client,
    db,
):
    group = create_group(slug="platform")
    team = create_team(group, slug="sre")
    route = create_route(
        team,
        source="webhook",
    )

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=sns_notification(),
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "route_source_mismatch",
        "message": "Route source must be aws_sns.",
    }


def test_aws_sns_cloudwatch_alarm_creates_alert_and_group(
    client,
    monkeypatch,
    db,
):
    route, team = create_aws_sns_route()

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        lambda envelope, expected_topic_arn: True,
    )

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=sns_notification("ALARM"),
    )

    assert response.status_code == 200

    body = response.get_json()

    assert isinstance(body, list)
    assert len(body) == 1

    result = body[0]

    assert result["created"] is True
    assert result["outcome"] == "created"
    assert result["processing_status"] == "completed"
    assert result["status"] == "firing"

    assert result["alert_id"]
    assert result["group_id"]
    assert result["trace_id"]

    assert result["team_id"] == team.id
    assert result["team_slug"] == team.slug
    assert result["route_id"] == route.id
    assert result["routing_error"] is None

    alert = Alert.get_by_id(result["alert_id"])
    alert_group = AlertGroup.get_by_id(
        result["group_id"]
    )

    assert alert.source == "aws_sns"
    assert alert.status == "firing"
    assert alert.route_id == route.id
    assert alert.team_id == team.id
    assert alert.group_id == alert_group.id

    assert alert.title == "HighCPU"
    assert alert.severity == "critical"

    assert alert.external_id == (
        "arn:aws:cloudwatch:eu-west-1:"
        "123456789012:alarm:HighCPU"
    )
    assert alert.dedup_key == alert.external_id

    assert alert.labels["aws_service"] == "cloudwatch"
    assert alert.labels["cloudwatch_state"] == "ALARM"
    assert alert.labels["cloudwatch_metric_name"] == (
        "CPUUtilization"
    )
    assert alert.labels["cloudwatch_namespace"] == "AWS/EC2"
    assert alert.labels["environment"] == "production"
    assert alert.labels["dimension_instanceid"] == (
        "i-0123456789abcdef0"
    )

    assert "Signature" not in alert.payload["sns"]
    assert alert.payload["cloudwatch"]["AlarmName"] == (
        "HighCPU"
    )

    assert alert_group.source == "aws_sns"
    assert alert_group.status == "firing"
    assert alert_group.route_id == route.id
    assert alert_group.team_id == team.id

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id
        == result["trace_id"]
    )

    assert trace.source == "aws_sns"
    assert trace.alert_id == alert.id
    assert trace.group_id == alert_group.id
    assert trace.status == "completed"
    assert trace.outcome == "created"


def test_aws_sns_cloudwatch_ok_resolves_existing_alert(
    client,
    monkeypatch,
    db,
):
    route, _team = create_aws_sns_route()

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        lambda envelope, expected_topic_arn: True,
    )

    alarm_response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=sns_notification("ALARM"),
    )

    assert alarm_response.status_code == 200

    alarm_result = alarm_response.get_json()[0]

    ok_envelope = sns_notification("OK")
    ok_envelope["MessageId"] = "sns-message-2"
    ok_envelope["Subject"] = "OK: HighCPU"
    ok_envelope["Timestamp"] = (
        "2026-06-21T10:15:01.000Z"
    )

    ok_response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=ok_envelope,
    )

    assert ok_response.status_code == 200

    ok_result = ok_response.get_json()[0]

    assert ok_result["created"] is False
    assert ok_result["outcome"] == "updated"
    assert ok_result["processing_status"] == "completed"
    assert ok_result["status"] == "resolved"
    assert ok_result["trace_id"]

    assert (
        ok_result["alert_id"]
        == alarm_result["alert_id"]
    )
    assert (
        ok_result["group_id"]
        == alarm_result["group_id"]
    )

    alert = Alert.get_by_id(
        alarm_result["alert_id"]
    )
    alert_group = AlertGroup.get_by_id(
        alarm_result["group_id"]
    )

    assert alert.status == "resolved"
    assert alert.severity == "info"
    assert alert.labels["cloudwatch_state"] == "OK"
    assert alert.labels["cloudwatch_previous_state"] == (
        "ALARM"
    )

    assert alert_group.status == "resolved"

    alarm_arn = (
        "arn:aws:cloudwatch:eu-west-1:"
        "123456789012:alarm:HighCPU"
    )

    assert (
        Alert.select()
        .where(
            (Alert.source == "aws_sns")
            & (Alert.dedup_key == alarm_arn)
        )
        .count()
        == 1
    )

    trace = AlertExplainTrace.get(
        AlertExplainTrace.trace_id
        == ok_result["trace_id"]
    )

    assert trace.alert_id == alert.id
    assert trace.group_id == alert_group.id
    assert trace.status == "completed"
    assert trace.outcome == "updated"


def sns_subscription_confirmation():
    return {
        "Type": "SubscriptionConfirmation",
        "MessageId": "sns-confirmation-1",
        "Token": "confirmation-token",
        "TopicArn": TOPIC_ARN,
        "Message": (
            "You have chosen to subscribe to the topic."
        ),
        "SubscribeURL": (
            "https://sns.eu-west-1.amazonaws.com/"
            "?Action=ConfirmSubscription"
            "&TopicArn="
            "arn%3Aaws%3Asns%3Aeu-west-1%3A"
            "123456789012%3Aincidentrelay-alerts"
            "&Token=confirmation-token"
        ),
        "Timestamp": "2026-06-21T09:00:00.000Z",
        "SignatureVersion": "2",
        "Signature": "placeholder",
        "SigningCertURL": CERT_URL,
    }

def test_aws_sns_endpoint_confirms_subscription(
    client,
    monkeypatch,
    db,
):
    route, _team = create_aws_sns_route()

    validated = []
    confirmations = []

    def fake_validate(
        envelope,
        expected_topic_arn,
    ):
        validated.append({
            "envelope": envelope,
            "topic_arn": expected_topic_arn,
        })
        return True

    def fake_confirm(
        subscribe_url,
        expected_topic_arn,
    ):
        confirmations.append({
            "subscribe_url": subscribe_url,
            "topic_arn": expected_topic_arn,
        })
        return True

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        fake_validate,
    )
    monkeypatch.setattr(
        "app.views.integrations_view."
        "confirm_aws_sns_subscription",
        fake_confirm,
    )

    payload = sns_subscription_confirmation()

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        headers={
            "x-amz-sns-message-type": (
                "SubscriptionConfirmation"
            ),
            "x-amz-sns-topic-arn": TOPIC_ARN,
        },
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "confirmed",
        "message_id": "sns-confirmation-1",
        "topic_arn": TOPIC_ARN,
    }

    assert len(validated) == 1
    assert validated[0]["topic_arn"] == TOPIC_ARN
    assert validated[0]["envelope"]["Type"] == (
        "SubscriptionConfirmation"
    )

    assert confirmations == [
        {
            "subscribe_url": payload["SubscribeURL"],
            "topic_arn": TOPIC_ARN,
        }
    ]

    assert (
        Alert.select()
        .where(Alert.source == "aws_sns")
        .count()
        == 0
    )


def test_aws_sns_endpoint_rejects_header_mismatch(
    client,
    monkeypatch,
    db,
):
    route, _team = create_aws_sns_route()

    calls = []

    def fake_validate(
        envelope,
        expected_topic_arn,
    ):
        calls.append(envelope)
        return True

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        fake_validate,
    )

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        headers={
            "x-amz-sns-message-type": "Notification",
            "x-amz-sns-topic-arn": (
                "arn:aws:sns:eu-west-1:"
                "123456789012:wrong-topic"
            ),
        },
        json=sns_notification(),
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "aws_sns_header_mismatch",
        "message": (
            "Amazon SNS Topic ARN header "
            "does not match the payload."
        ),
    }

    assert calls == []


def test_aws_sns_endpoint_rejects_topic_mismatch(
    client,
    monkeypatch,
    db,
):
    route, _team = create_aws_sns_route()

    def reject_topic(
        envelope,
        expected_topic_arn,
    ):
        raise AwsSnsError(
            "aws_sns_topic_mismatch",
            (
                "Amazon SNS Topic ARN does not "
                "match this route."
            ),
            403,
        )

    monkeypatch.setattr(
        "app.views.integrations_view."
        "validate_aws_sns_message",
        reject_topic,
    )

    response = client.post(
        f"/api/integrations/aws-sns/{route.id}",
        json=sns_notification(),
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "aws_sns_topic_mismatch",
        "message": (
            "Amazon SNS Topic ARN does not "
            "match this route."
        ),
    }


def test_validate_confirmation_url_accepts_expected_topic():
    parsed = validate_confirmation_url(
        sns_subscription_confirmation()[
            "SubscribeURL"
        ],
        TOPIC_ARN,
    )

    assert parsed.scheme == "https"
    assert parsed.hostname == (
        "sns.eu-west-1.amazonaws.com"
    )


def test_validate_confirmation_url_rejects_wrong_topic():
    url = (
        "https://sns.eu-west-1.amazonaws.com/"
        "?Action=ConfirmSubscription"
        "&TopicArn="
        "arn%3Aaws%3Asns%3Aeu-west-1%3A"
        "123456789012%3Awrong-topic"
        "&Token=confirmation-token"
    )

    with pytest.raises(
        AwsSnsError,
        match="Topic ARN does not match",
    ):
        validate_confirmation_url(
            url,
            TOPIC_ARN,
        )
