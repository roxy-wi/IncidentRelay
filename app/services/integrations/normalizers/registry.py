"""Shared registry for integration payload normalizers.

Both production ingestion and Event Orchestration simulation use this module,
so adding a normalizer requires updating one registry only.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Mapping, Optional

from app.services.integrations.normalizers.alertmanager import normalize_alertmanager
from app.services.integrations.normalizers.aws_sns import normalize_aws_sns
from app.services.integrations.normalizers.datadog import normalize_datadog
from app.services.integrations.normalizers.grafana import normalize_grafana
from app.services.integrations.normalizers.librenms import normalize_librenms
from app.services.integrations.normalizers.new_relic import normalize_new_relic
from app.services.integrations.normalizers.rmon import normalize_rmon
from app.services.integrations.normalizers.sentry import normalize_sentry
from app.services.integrations.normalizers.uptime_kuma import normalize_uptime_kuma
from app.services.integrations.normalizers.webhook import normalize_webhook
from app.services.integrations.normalizers.zabbix import normalize_zabbix


class UnknownNormalizerSource(ValueError):
    """Raised when no payload normalizer is registered for a source."""


Normalizer = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    Any,
]


def _payload_only(normalizer: Callable[[Mapping[str, Any]], Any]) -> Normalizer:
    def wrapped(
        payload: Mapping[str, Any],
        headers: Mapping[str, Any],
        route_config: Mapping[str, Any],
    ) -> Any:
        del headers, route_config
        return normalizer(payload)

    return wrapped


def _normalize_sentry(
    payload: Mapping[str, Any],
    headers: Mapping[str, Any],
    route_config: Mapping[str, Any],
) -> Any:
    return normalize_sentry(
        payload,
        headers=dict(headers),
        route_config=dict(route_config),
    )


_NORMALIZERS: Dict[str, Normalizer] = {
    "alertmanager": _payload_only(normalize_alertmanager),
    "aws_sns": _payload_only(normalize_aws_sns),
    "datadog": _payload_only(normalize_datadog),
    "grafana": _payload_only(normalize_grafana),
    "librenms": _payload_only(normalize_librenms),
    "new_relic": _payload_only(normalize_new_relic),
    "rmon": _payload_only(normalize_rmon),
    "sentry": _normalize_sentry,
    "uptime_kuma": _payload_only(normalize_uptime_kuma),
    "webhook": _payload_only(normalize_webhook),
    "zabbix": _payload_only(normalize_zabbix),
}

SUPPORTED_NORMALIZER_SOURCES = frozenset(_NORMALIZERS)


def get_normalizer(source: str) -> Normalizer:
    normalized_source = str(source or "").strip().lower()
    normalizer = _NORMALIZERS.get(normalized_source)
    if normalizer is None:
        raise UnknownNormalizerSource(
            f"Unsupported integration source: {normalized_source or '<empty>'}"
        )
    return normalizer


def normalize_for_source(
    source: str,
    payload: Mapping[str, Any],
    *,
    headers: Optional[Mapping[str, Any]] = None,
    route_config: Optional[Mapping[str, Any]] = None,
    copy_payload: bool = False,
) -> Any:
    """Normalize a payload through the registered source adapter.

    Production ingestion may pass validated payloads directly. Simulation sets
    ``copy_payload=True`` to guarantee that a normalizer cannot mutate the
    caller's input.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be an object")

    source_key = str(source or "").strip().lower()
    normalizer = get_normalizer(source_key)
    normalized_payload = copy.deepcopy(dict(payload)) if copy_payload else payload

    return normalizer(
        normalized_payload,
        dict(headers or {}),
        dict(route_config or {}),
    )


__all__ = [
    "SUPPORTED_NORMALIZER_SOURCES",
    "UnknownNormalizerSource",
    "get_normalizer",
    "normalize_for_source",
]
