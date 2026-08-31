#!/usr/bin/env python3
"""Send Nagios Core/XI notification environment macros to IncidentRelay."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def _env(name):
    value = os.environ.get(f"NAGIOS_{name}")
    if value is None:
        return None
    value = value.strip()
    return value or None


def build_payload():
    service_description = _env("SERVICEDESC")
    payload = {
        "notification_type": _env("NOTIFICATIONTYPE"),
        "host_name": _env("HOSTNAME"),
        "host_alias": _env("HOSTALIAS"),
        "host_address": _env("HOSTADDRESS"),
        "host_state": _env("HOSTSTATE"),
        "host_output": _env("HOSTOUTPUT"),
        "long_host_output": _env("LONGHOSTOUTPUT"),
        "service_description": service_description,
        "service_state": _env("SERVICESTATE"),
        "service_output": _env("SERVICEOUTPUT"),
        "long_service_output": _env("LONGSERVICEOUTPUT"),
        "state_type": (
            _env("SERVICESTATETYPE")
            if service_description
            else _env("HOSTSTATETYPE")
        ),
        "event_link": (
            _env("SERVICEACTIONURL")
            if service_description
            else _env("HOSTACTIONURL")
        ),
    }
    return {key: value for key, value in payload.items() if value is not None}


def main():
    args = parse_args()
    payload = build_payload()
    if not payload.get("host_name"):
        sys.stderr.write("NAGIOS_HOSTNAME is missing\n")
        return 2

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.token}",
            "Content-Type": "application/json",
            "User-Agent": "IncidentRelay-Nagios/1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            response.read()
            return 0 if 200 <= response.status < 300 else 2
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"IncidentRelay returned HTTP {exc.code}\n")
        return 2
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        sys.stderr.write(f"IncidentRelay notification failed: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
