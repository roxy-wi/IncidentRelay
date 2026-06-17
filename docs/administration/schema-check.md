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
- email channels should not document channel-level recipients or SMTP transport fields.

Recommended local checks:

```bash
pytest tests
python3 -m compileall -q app tests
```
