import json
import re

from app.services.integrations.normalizers.common import (
    clean_string,
    first_non_empty,
    make_dedup_key,
)


CLOUDWATCH_RESOLVED_STATES = {
    "OK",
}

CLOUDWATCH_FIRING_STATES = {
    "ALARM",
    "INSUFFICIENT_DATA",
}


def _label_key(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    return value.strip("_")


def _set_label(labels, key, value):
    key = _label_key(key)
    value = clean_string(value)

    if key and value is not None:
        labels.setdefault(key, value)


def _message_attribute_value(
    envelope,
    name,
):
    attributes = envelope.get(
        "MessageAttributes"
    ) or {}

    item = attributes.get(name)

    if item is None:
        for key, candidate in attributes.items():
            if str(key).lower() == name.lower():
                item = candidate
                break

    if isinstance(item, dict):
        return first_non_empty(
            item.get("Value"),
            item.get("StringValue"),
        )

    return clean_string(item)


def _sns_labels(envelope):
    labels = {}

    _set_label(
        labels,
        "sns_topic_arn",
        envelope.get("TopicArn"),
    )
    _set_label(
        labels,
        "sns_message_id",
        envelope.get("MessageId"),
    )

    attributes = envelope.get(
        "MessageAttributes"
    ) or {}

    for name, item in attributes.items():
        if isinstance(item, dict):
            value = first_non_empty(
                item.get("Value"),
                item.get("StringValue"),
            )
        else:
            value = item

        _set_label(labels, name, value)

    return labels


def _cloudwatch_status(state):
    state = str(state or "").strip().upper()

    if state in CLOUDWATCH_RESOLVED_STATES:
        return "resolved"

    return "firing"


def _cloudwatch_severity(
    state,
    envelope,
):
    configured = first_non_empty(
        _message_attribute_value(
            envelope,
            "severity",
        ),
    )

    if configured:
        return configured

    state = str(state or "").strip().upper()

    if state == "ALARM":
        return "critical"

    if state == "INSUFFICIENT_DATA":
        return "warning"

    return "info"


def _safe_stored_envelope(envelope):
    return {
        key: value
        for key, value in envelope.items()
        if key not in {
            "Signature",
        }
    }


def _normalize_cloudwatch_alarm(
    envelope,
    message,
):
    labels = _sns_labels(envelope)

    state = str(
        message.get("NewStateValue") or ""
    ).strip().upper()

    alarm_name = first_non_empty(
        message.get("AlarmName"),
        envelope.get("Subject"),
        "CloudWatch alarm",
    )

    alarm_arn = clean_string(
        message.get("AlarmArn")
    )

    account_id = clean_string(
        message.get("AWSAccountId")
    )
    region = clean_string(
        message.get("Region")
    )

    _set_label(
        labels,
        "alertname",
        alarm_name,
    )
    _set_label(
        labels,
        "aws_service",
        "cloudwatch",
    )
    _set_label(
        labels,
        "aws_account_id",
        account_id,
    )
    _set_label(
        labels,
        "aws_region",
        region,
    )
    _set_label(
        labels,
        "cloudwatch_alarm_arn",
        alarm_arn,
    )
    _set_label(
        labels,
        "cloudwatch_state",
        state,
    )
    _set_label(
        labels,
        "cloudwatch_previous_state",
        message.get("OldStateValue"),
    )

    trigger = message.get("Trigger") or {}

    if isinstance(trigger, dict):
        _set_label(
            labels,
            "cloudwatch_metric_name",
            trigger.get("MetricName"),
        )
        _set_label(
            labels,
            "cloudwatch_namespace",
            trigger.get("Namespace"),
        )
        _set_label(
            labels,
            "cloudwatch_statistic",
            first_non_empty(
                trigger.get("Statistic"),
                trigger.get("StatisticType"),
            ),
        )
        _set_label(
            labels,
            "cloudwatch_unit",
            trigger.get("Unit"),
        )
        _set_label(
            labels,
            "cloudwatch_period",
            trigger.get("Period"),
        )
        _set_label(
            labels,
            "cloudwatch_evaluation_periods",
            trigger.get("EvaluationPeriods"),
        )
        _set_label(
            labels,
            "cloudwatch_datapoints_to_alarm",
            trigger.get("DatapointsToAlarm"),
        )
        _set_label(
            labels,
            "cloudwatch_comparison_operator",
            trigger.get("ComparisonOperator"),
        )
        _set_label(
            labels,
            "cloudwatch_threshold",
            trigger.get("Threshold"),
        )
        _set_label(
            labels,
            "cloudwatch_treat_missing_data",
            trigger.get("TreatMissingData"),
        )

        for dimension in (
            trigger.get("Dimensions") or []
        ):
            if not isinstance(dimension, dict):
                continue

            dimension_name = _label_key(
                dimension.get("name")
            )

            if not dimension_name:
                continue

            _set_label(
                labels,
                f"dimension_{dimension_name}",
                dimension.get("value"),
            )

    severity = _cloudwatch_severity(
        state,
        envelope,
    )

    _set_label(
        labels,
        "severity",
        severity,
    )

    external_id = first_non_empty(
        alarm_arn,
        message.get("AlarmName"),
        envelope.get("MessageId"),
    )

    dedup_key = alarm_arn or make_dedup_key(
        "aws_sns",
        external_id,
        alarm_name,
        labels,
    )

    annotations = {
        "alarm_description": message.get(
            "AlarmDescription"
        ),
        "state_reason": message.get(
            "NewStateReason"
        ),
        "state_change_time": message.get(
            "StateChangeTime"
        ),
        "alarm_rule": message.get(
            "AlarmRule"
        ),
        "triggering_children": message.get(
            "TriggeringChildren"
        ),
    }

    annotations = {
        key: value
        for key, value in annotations.items()
        if value not in (None, "", [])
    }

    return {
        "source": "aws_sns",
        "team_slug": first_non_empty(
            _message_attribute_value(
                envelope,
                "team",
            ),
            _message_attribute_value(
                envelope,
                "oncall_team",
            ),
            labels.get("team"),
            labels.get("oncall_team"),
        ),
        "external_id": external_id,
        "dedup_key": dedup_key,
        "title": alarm_name,
        "message": first_non_empty(
            message.get("NewStateReason"),
            message.get("AlarmDescription"),
            alarm_name,
        ),
        "severity": severity,
        "labels": labels,
        "annotations": annotations,
        "payload": {
            "sns": _safe_stored_envelope(
                envelope
            ),
            "cloudwatch": message,
        },
        "status": _cloudwatch_status(state),
    }


def _normalize_generic_sns(
    envelope,
    parsed_message,
):
    labels = _sns_labels(envelope)

    _set_label(
        labels,
        "aws_service",
        "sns",
    )

    title = first_non_empty(
        envelope.get("Subject"),
        "AWS SNS notification",
    )

    if isinstance(parsed_message, str):
        message_text = parsed_message
    else:
        message_text = json.dumps(
            parsed_message,
            ensure_ascii=False,
            sort_keys=True,
        )

    external_id = clean_string(
        envelope.get("MessageId")
    )

    return {
        "source": "aws_sns",
        "team_slug": first_non_empty(
            labels.get("team"),
            labels.get("oncall_team"),
        ),
        "external_id": external_id,
        "dedup_key": external_id or make_dedup_key(
            "aws_sns",
            external_id,
            title,
            labels,
        ),
        "title": title,
        "message": message_text,
        "severity": first_non_empty(
            labels.get("severity"),
            "warning",
        ),
        "labels": labels,
        "payload": {
            "sns": _safe_stored_envelope(
                envelope
            ),
            "message": parsed_message,
        },
        "status": "firing",
    }


def normalize_aws_sns(envelope):
    """Normalize an SNS Notification envelope."""
    raw_message = envelope.get("Message") or ""

    try:
        parsed_message = json.loads(raw_message)
    except (TypeError, json.JSONDecodeError):
        parsed_message = raw_message

    if (
        isinstance(parsed_message, dict)
        and parsed_message.get("AlarmName")
        and parsed_message.get("NewStateValue")
    ):
        return [
            _normalize_cloudwatch_alarm(
                envelope,
                parsed_message,
            )
        ]

    return [
        _normalize_generic_sns(
            envelope,
            parsed_message,
        )
    ]
