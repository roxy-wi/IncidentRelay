---
title: Schema Check
description: Check the IncidentRelay database schema after migrations.
---

# Schema Check

Keep request schemas, OpenAPI documentation and UI forms aligned.

Common checks:

- if a field exists in Swagger request body, it should exist in the matching request schema;
- if a schema rejects a field because `extra="forbid"`, Swagger should not advertise that field;
- enum values should use the same constants as backend validation;
- old role values such as `read_only` and `rw` should not appear in request schemas after migration;
- email channel recipient_mode and recipient_email must match schema validation; SMTP transport fields remain global (never per channel).

Recommended local checks:

```bash
pytest tests
python3 -m compileall -q app tests
```
