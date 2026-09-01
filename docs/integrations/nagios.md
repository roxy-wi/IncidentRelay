# Nagios Core / Nagios XI

IncidentRelay can receive host and service notifications from Nagios Core and Nagios XI at:

```text
POST /api/integrations/nagios
```

Create a Route with source **Nagios**, then use its intake token as an `Authorization: Bearer` token.

## Lifecycle mapping

| Nagios notification | IncidentRelay |
|---|---|
| `PROBLEM` | firing alert |
| `RECOVERY` or state `OK` / `UP` | resolved alert |
| `ACKNOWLEDGEMENT` | acknowledge the matching IncidentRelay alert group |
| flapping / downtime / custom notifications | accepted and ignored |

Host alerts deduplicate by host. Service alerts deduplicate by host + service description, so a later recovery updates the original alert instead of creating a new one.

## Recommended sender

The repository includes `examples/nagios/incidentrelay_notify.py`. It uses only the Python standard library and safely JSON-encodes Nagios macro values, including quotes and multi-line plugin output.

Copy it to the Nagios plugin directory, for example:

```bash
install -m 0755 examples/nagios/incidentrelay_notify.py \
  /usr/local/nagios/libexec/incidentrelay_notify.py
```

Store the IncidentRelay URL and route token in `resource.cfg` using unused `$USERn$` macros:

```text
$USER10$=https://incidentrelay.example.com/api/integrations/nagios
$USER11$=YOUR_ROUTE_INTAKE_TOKEN
```

### Notification command

Nagios exposes most standard macros to notification scripts as `NAGIOS_*` environment variables. The bundled sender reads those variables directly, so plugin output does not need to be interpolated into the shell command line. `$USERn$` resource macros are used only for the controlled URL/token values.

```text
define command {
    command_name notify-by-incidentrelay
    command_line /usr/bin/python3 /usr/local/nagios/libexec/incidentrelay_notify.py --url '$USER10$' --token '$USER11$'
}
```

Use `notify-by-incidentrelay` as both the host and service notification command for the desired contacts/contact groups. For Nagios XI, create the same command in **Core Config Manager → Commands**.

Keep Nagios macro cleansing enabled (`illegal_macro_output_chars`) as recommended by Nagios, even though the sender reads the already-exported notification environment instead of placing plugin output directly in the command line.

## Direct JSON example

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/nagios' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "notification_type": "PROBLEM",
    "host_name": "db01",
    "host_address": "10.10.20.15",
    "service_description": "Disk Usage",
    "service_state": "CRITICAL",
    "service_output": "/var is 96% full"
  }'
```

The normalized alert exposes matcher-friendly labels such as `nagios_host`, `nagios_service`, `nagios_state`, `nagios_notification_type` and `nagios_object_type`.
